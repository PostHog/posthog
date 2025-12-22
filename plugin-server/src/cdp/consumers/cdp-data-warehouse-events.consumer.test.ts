import { mockProducerObserver } from '../../../tests/helpers/mocks/producer.mock'

import { createOrganization, createTeam, getFirstTeam, getTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import { insertHogFunction as _insertHogFunction, createKafkaMessage } from '../_tests/fixtures'
import { CdpDataWarehouseEvent } from '../schema'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { HogWatcherState } from '../services/monitoring/hog-watcher.service'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../types'
import { CdpDatawarehouseEventsConsumer } from './cdp-data-warehouse-events.consumer'

jest.setTimeout(1000)

describe('CdpDatawarehouseEventsConsumer', () => {
    let processor: CdpDatawarehouseEventsConsumer
    let hub: Hub
    let team: Team
    let team2: Team
    let mockQueueInvocations: jest.Mock

    const createDataWarehouseEvent = (teamId: number, properties: Record<string, any> = {}): CdpDataWarehouseEvent => {
        return {
            team_id: teamId,
            properties: {
                column1: 'value1',
                column2: 123,
                ...properties,
            },
        }
    }

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const teamId = hogFunction.team_id ?? team.id
        const item = await _insertHogFunction(hub.postgres, teamId, {
            ...hogFunction,
            type: 'destination',
        })
        // Trigger the reload that django would do
        processor['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [item.id])
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub) // This team has data_pipelines feature by default (legacy addon)

        // Create second organization without data_pipelines for testing quota limiting
        const otherOrganizationId = await createOrganization(hub.postgres)
        const team2Id = await createTeam(hub.postgres, otherOrganizationId)
        team2 = (await getTeam(hub, team2Id))! // This team does NOT have data_pipelines

        // Set up default quota limiting mock - not limited by default
        jest.spyOn(hub.quotaLimiting, 'isTeamQuotaLimited').mockResolvedValue(false)

        processor = new CdpDatawarehouseEventsConsumer(hub)

        // NOTE: We don't want to actually connect to Kafka for these tests as it is slow and we are testing the core logic only
        processor['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(() => ({ status: 'healthy' })),
        } as any

        processor['cyclotronJobQueue'] = {
            queueInvocations: jest.fn(),
            startAsProducer: jest.fn(() => Promise.resolve()),
            stop: jest.fn(),
        } as unknown as jest.Mocked<CyclotronJobQueue>

        mockQueueInvocations = jest.mocked(processor['cyclotronJobQueue']['queueInvocations'])

        await processor.start()
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await processor.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('_parseKafkaBatch', () => {
        it('should parse valid data warehouse events', async () => {
            await insertHogFunction({
                team_id: team.id,
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch_data_warehouse_table,
                ...HOG_FILTERS_EXAMPLES.no_filters_data_warehouse_table,
            })

            const event = createDataWarehouseEvent(team.id, { test_prop: 'test_value' })
            const messages = [createKafkaMessage(event)]

            const invocations = await processor._parseKafkaBatch(messages)

            expect(invocations).toHaveLength(1)
            expect(invocations[0].project.id).toBe(team.id)
            expect(invocations[0].event.properties).toMatchObject({
                column1: 'value1',
                column2: 123,
                test_prop: 'test_value',
            })
            expect(invocations[0].event.uuid).toBe('data-warehouse-table-uuid-do-not-use')
            expect(invocations[0].event.event).toBe('data-warehouse-table-event-do-not-use')
        })

        it('should not parse events for teams without hog functions or flows', async () => {
            const event = createDataWarehouseEvent(team.id)
            const messages = [createKafkaMessage(event)]

            const invocations = await processor._parseKafkaBatch(messages)

            expect(invocations).toHaveLength(0)
        })

        it('should not parse events for teams that do not exist', async () => {
            await insertHogFunction({
                team_id: team.id,
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch_data_warehouse_table,
                ...HOG_FILTERS_EXAMPLES.no_filters_data_warehouse_table,
            })

            const event = createDataWarehouseEvent(99999)
            const messages = [createKafkaMessage(event)]

            const invocations = await processor._parseKafkaBatch(messages)

            expect(invocations).toHaveLength(0)
        })

        it('should handle schema validation errors gracefully', async () => {
            const invalidEvent = { team_id: 'not-a-number' }
            const messages = [createKafkaMessage(invalidEvent)]

            const invocations = await processor._parseKafkaBatch(messages)

            expect(invocations).toHaveLength(0)
        })

        it('should filter by team correctly', async () => {
            await insertHogFunction({
                team_id: team.id,
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch_data_warehouse_table,
                ...HOG_FILTERS_EXAMPLES.no_filters_data_warehouse_table,
            })

            const events = [
                createKafkaMessage(createDataWarehouseEvent(team.id)),
                createKafkaMessage(createDataWarehouseEvent(team2.id)),
            ]

            const invocations = await processor._parseKafkaBatch(events)

            expect(invocations).toHaveLength(1)
            expect(invocations[0].project.id).toBe(team.id)

            await insertHogFunction({
                team_id: team2.id,
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch_data_warehouse_table,
                ...HOG_FILTERS_EXAMPLES.no_filters_data_warehouse_table,
            })

            const invocations2 = await processor._parseKafkaBatch(events)
            expect(invocations2).toHaveLength(2)
        })
    })

    describe('filterHogFunction', () => {
        it('should filter for data-warehouse-table source', async () => {
            const fnWithDataWarehouseFilter = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch_data_warehouse_table,
                ...HOG_FILTERS_EXAMPLES.no_filters_data_warehouse_table,
            })

            await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch_data_warehouse_table,
                ...HOG_FILTERS_EXAMPLES.no_filters,
                filters: { ...HOG_FILTERS_EXAMPLES.no_filters.filters, source: 'events' },
            })

            await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch_data_warehouse_table,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const event = createDataWarehouseEvent(team.id)
            const messages = [createKafkaMessage(event)]
            const globals = await processor._parseKafkaBatch(messages)

            const { invocations } = await processor.processBatch(globals)

            // Should only include the function with data-warehouse-table filter
            expect(invocations).toHaveLength(1)
            expect(invocations[0].teamId).toBe(fnWithDataWarehouseFilter.team_id)
        })
    })

    describe('processBatch', () => {
        let fnFetchNoFilters: HogFunctionType
        let globals: HogFunctionInvocationGlobals

        beforeEach(async () => {
            fnFetchNoFilters = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch_data_warehouse_table,
                ...HOG_FILTERS_EXAMPLES.no_filters_data_warehouse_table,
            })

            const event = createDataWarehouseEvent(team.id, { test_prop: 'test_value' })
            const messages = [createKafkaMessage(event)]
            globals = (await processor._parseKafkaBatch(messages))[0]
        })

        it('should process data warehouse events and create invocations', async () => {
            const { invocations } = await processor.processBatch([globals])

            expect(invocations).toHaveLength(1)
            expect(invocations[0].teamId).toBe(fnFetchNoFilters.team_id)
            expect(invocations[0].state?.globals.event.properties).toMatchObject({
                column1: 'value1',
                column2: 123,
                test_prop: 'test_value',
            })

            expect(mockQueueInvocations).toHaveBeenCalledWith(invocations)
        })

        it('should return empty invocations for empty batch', async () => {
            const { invocations } = await processor.processBatch([])

            expect(invocations).toHaveLength(0)
            expect(mockQueueInvocations).not.toHaveBeenCalled()
        })

        it('should filter out disabled hog functions', async () => {
            await processor.hogWatcher.forceStateChange(fnFetchNoFilters, HogWatcherState.disabled)

            const { invocations } = await processor.processBatch([globals])

            expect(invocations).toHaveLength(0)
            expect(mockQueueInvocations).toHaveBeenCalledWith([])

            expect(mockProducerObserver.getProducedKafkaMessages()).toMatchObject([
                {
                    topic: 'clickhouse_app_metrics2_test',
                    value: {
                        app_source: 'hog_function',
                        app_source_id: fnFetchNoFilters.id,
                        count: 1,
                        metric_kind: 'failure',
                        metric_name: 'disabled_permanently',
                        team_id: team.id,
                    },
                },
            ])
        })

        it('should handle degraded state by setting queue priority', async () => {
            await processor.hogWatcher.forceStateChange(fnFetchNoFilters, HogWatcherState.degraded)

            const { invocations } = await processor.processBatch([globals])

            expect(invocations).toHaveLength(1)
            expect(invocations[0].queuePriority).toBe(2)
        })

        it('should log correct metrics for triggered invocations', async () => {
            const { invocations } = await processor.processBatch([globals])

            expect(invocations).toHaveLength(1)

            expect(mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_app_metrics2_test')).toMatchObject(
                [
                    {
                        key: expect.any(String),
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: fnFetchNoFilters.id,
                            count: 1,
                            metric_kind: 'other',
                            metric_name: 'triggered',
                            team_id: team.id,
                            timestamp: expect.any(String),
                        },
                    },
                    {
                        key: expect.any(String),
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: fnFetchNoFilters.id,
                            count: 1,
                            metric_kind: 'billing',
                            metric_name: 'billable_invocation',
                            team_id: team.id,
                            timestamp: expect.any(String),
                        },
                    },
                ]
            )
        })
    })

    describe('quota limiting', () => {
        let fnFetchNoFilters: HogFunctionType
        let fnDataWarehouseFunction: HogFunctionType
        let globals: HogFunctionInvocationGlobals

        beforeEach(async () => {
            // Create functions for team2 (no data_pipelines feature)
            fnFetchNoFilters = await insertHogFunction({
                team_id: team2.id,
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch_data_warehouse_table,
                ...HOG_FILTERS_EXAMPLES.no_filters_data_warehouse_table,
            })

            fnDataWarehouseFunction = await insertHogFunction({
                team_id: team2.id,
                ...HOG_EXAMPLES.input_printer,
                ...HOG_INPUTS_EXAMPLES.simple_fetch_data_warehouse_table,
                ...HOG_FILTERS_EXAMPLES.no_filters_data_warehouse_table,
            })

            // Globals for team2 (without data_pipelines)
            const event = createDataWarehouseEvent(team2.id, { test_prop: 'test_value' })
            const messages = [createKafkaMessage(event)]
            globals = (await processor._parseKafkaBatch(messages))[0]
        })

        it('should filter out functions when team is quota limited', async () => {
            // Mock quota limiting to return true for team2 (which doesn't have data_pipelines)
            jest.mocked(hub.quotaLimiting.isTeamQuotaLimited).mockClear()
            jest.mocked(hub.quotaLimiting.isTeamQuotaLimited).mockResolvedValue(true)

            const { invocations } = await processor.processBatch([globals])

            expect(hub.quotaLimiting.isTeamQuotaLimited).toHaveBeenCalledWith(team2.id, 'cdp_trigger_events')

            // Now check invocations length - should be 0 because team2 is quota limited and has no legacy addon
            expect(invocations).toHaveLength(0)

            // Check that quota_limited metrics were produced
            const metrics = mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_app_metrics2_test')
            expect(metrics).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        topic: 'clickhouse_app_metrics2_test',
                        value: expect.objectContaining({
                            app_source: 'hog_function',
                            app_source_id: fnFetchNoFilters.id,
                            count: 1,
                            metric_kind: 'failure',
                            metric_name: 'quota_limited',
                            team_id: team2.id,
                        }),
                    }),
                    expect.objectContaining({
                        topic: 'clickhouse_app_metrics2_test',
                        value: expect.objectContaining({
                            app_source: 'hog_function',
                            app_source_id: fnDataWarehouseFunction.id,
                            count: 1,
                            metric_kind: 'failure',
                            metric_name: 'quota_limited',
                            team_id: team2.id,
                        }),
                    }),
                ])
            )
        })

        it('should not filter out functions when team is not quota limited', async () => {
            // Mock quota limiting to return false for team2
            jest.mocked(hub.quotaLimiting.isTeamQuotaLimited).mockClear()
            jest.mocked(hub.quotaLimiting.isTeamQuotaLimited).mockResolvedValue(false)

            const { invocations } = await processor.processBatch([globals])

            expect(invocations).toHaveLength(2)
            expect(hub.quotaLimiting.isTeamQuotaLimited).toHaveBeenCalledWith(team2.id, 'cdp_trigger_events')

            // Check that triggered metrics were produced instead
            const metrics = mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_app_metrics2_test')
            expect(metrics).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        topic: 'clickhouse_app_metrics2_test',
                        value: expect.objectContaining({
                            app_source: 'hog_function',
                            app_source_id: fnFetchNoFilters.id,
                            count: 1,
                            metric_kind: 'other',
                            metric_name: 'triggered',
                            team_id: team2.id,
                        }),
                    }),
                    expect.objectContaining({
                        topic: 'clickhouse_app_metrics2_test',
                        value: expect.objectContaining({
                            app_source: 'hog_function',
                            app_source_id: fnDataWarehouseFunction.id,
                            count: 1,
                            metric_kind: 'other',
                            metric_name: 'triggered',
                            team_id: team2.id,
                        }),
                    }),
                ])
            )
        })
    })
})
