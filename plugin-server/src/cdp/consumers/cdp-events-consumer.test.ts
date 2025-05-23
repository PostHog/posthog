// eslint-disable-next-line simple-import-sort/imports
import { mockProducerObserver } from '../../../tests/helpers/mocks/producer.mock'

import { HogWatcherState } from '../services/hog-watcher.service'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../types'
import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import {
    createHogExecutionGlobals,
    insertHogFunction as _insertHogFunction,
    createKafkaMessage,
    createIncomingEvent,
    createInternalEvent,
} from '../_tests/fixtures'
import { CdpEventsConsumer } from './cdp-events.consumer'
import { CdpInternalEventsConsumer } from './cdp-internal-event.consumer'
import { CyclotronJobQueueKind } from '../services/job-queue/job-queue'

jest.setTimeout(1000)

/**
 * NOTE: The internal and normal events consumers are very similar so we can test them together
 */
describe.each([
    [CdpEventsConsumer.name, CdpEventsConsumer, 'destination' as const],
    [CdpInternalEventsConsumer.name, CdpInternalEventsConsumer, 'internal_destination' as const],
])('%s', (_name, Consumer, hogType) => {
    let processor: CdpEventsConsumer | CdpInternalEventsConsumer
    let hub: Hub
    let team: Team
    let team2: Team
    let mockQueueInvocations: jest.Mock

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const teamId = hogFunction.team_id ?? team.id
        const item = await _insertHogFunction(hub.postgres, teamId, {
            ...hogFunction,
            type: hogType,
        })
        // Trigger the reload that django would do
        processor['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [item.id])
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        const team2Id = await createTeam(hub.postgres, team.organization_id)
        team2 = (await getTeam(hub, team2Id))!

        processor = new Consumer(hub)

        // NOTE: We don't want to actually connect to Kafka for these tests as it is slow and we are testing the core logic only
        processor['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(),
        } as any

        processor['cyclotronJobQueue'] = {
            queueInvocations: jest.fn(),
            startAsProducer: jest.fn(() => Promise.resolve()),
            stop: jest.fn(),
        } as unknown as jest.Mocked<CyclotronJobQueueKind>

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

    describe('team filtering', () => {
        it('should not parse events for teams without hog functions', async () => {
            await insertHogFunction({
                team_id: team.id,
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const events =
                processor instanceof CdpInternalEventsConsumer
                    ? [
                          createKafkaMessage(createInternalEvent(team.id, {})),
                          createKafkaMessage(createInternalEvent(team2.id, {})),
                      ]
                    : [
                          createKafkaMessage(createIncomingEvent(team.id, {})),
                          createKafkaMessage(createIncomingEvent(team2.id, {})),
                      ]
            const invocations = await processor._parseKafkaBatch(events)
            expect(invocations).toHaveLength(1)
            expect(invocations[0].project.id).toBe(team.id)

            await insertHogFunction({
                team_id: team2.id,
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const invocations2 = await processor._parseKafkaBatch(events)
            expect(invocations2).toHaveLength(2)
        })
    })

    describe('general event processing', () => {
        describe('common processing', () => {
            let fnFetchNoFilters: HogFunctionType
            let fnPrinterPageviewFilters: HogFunctionType
            let globals: HogFunctionInvocationGlobals

            beforeEach(async () => {
                fnFetchNoFilters = await insertHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.no_filters,
                })

                fnPrinterPageviewFilters = await insertHogFunction({
                    ...HOG_EXAMPLES.input_printer,
                    ...HOG_INPUTS_EXAMPLES.secret_inputs,
                    ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                })

                globals = createHogExecutionGlobals({
                    project: {
                        id: team.id,
                    } as any,
                    event: {
                        uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                        event: '$pageview',
                        properties: {
                            $current_url: 'https://posthog.com',
                            $lib_version: '1.0.0',
                        },
                    } as any,
                })
            })

            const matchInvocation = (hogFunction: HogFunctionType, globals: HogFunctionInvocationGlobals) => {
                return {
                    hogFunction: {
                        id: hogFunction.id,
                    },
                    globals: {
                        event: globals.event,
                    },
                }
            }

            it('should process events', async () => {
                const { invocations } = await processor.processBatch([globals])

                expect(invocations).toHaveLength(2)
                expect(invocations).toMatchObject([
                    matchInvocation(fnFetchNoFilters, globals),
                    matchInvocation(fnPrinterPageviewFilters, globals),
                ])

                // Verify Cyclotron jobs
                expect(mockQueueInvocations).toHaveBeenCalledWith(invocations)
            })

            it("should filter out functions that don't match the filter", async () => {
                globals.event.properties.$current_url = 'https://nomatch.com'

                const { invocations } = await processor.processBatch([globals])

                expect(invocations).toHaveLength(1)
                expect(invocations).toMatchObject([matchInvocation(fnFetchNoFilters, globals)])

                // Verify only one Cyclotron job is created (for fnFetchNoFilters)
                expect(mockQueueInvocations).toHaveBeenCalledWith(invocations)

                // Still verify the metric for the filtered function
                expect(
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_app_metrics2_test')
                ).toMatchObject([
                    {
                        key: expect.any(String),
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: fnPrinterPageviewFilters.id,
                            count: 1,
                            metric_kind: 'other',
                            metric_name: 'filtered',
                            team_id: 2,
                            timestamp: expect.any(String),
                        },
                    },
                ])
            })

            it.each([
                [HogWatcherState.disabledForPeriod, 'disabled_temporarily'],
                [HogWatcherState.disabledIndefinitely, 'disabled_permanently'],
            ])('should filter out functions that are disabled', async (state, metric_name) => {
                await processor.hogWatcher.forceStateChange(fnFetchNoFilters.id, state)
                await processor.hogWatcher.forceStateChange(fnPrinterPageviewFilters.id, state)

                const { invocations } = await processor.processBatch([globals])

                expect(invocations).toHaveLength(0)
                expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(2)

                expect(mockProducerObserver.getProducedKafkaMessages()).toMatchObject([
                    {
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: fnFetchNoFilters.id,
                            count: 1,
                            metric_kind: 'failure',
                            metric_name: metric_name,
                            team_id: 2,
                        },
                    },
                    {
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: fnPrinterPageviewFilters.id,
                            count: 1,
                            metric_kind: 'failure',
                            metric_name: metric_name,
                            team_id: 2,
                        },
                    },
                ])
            })
        })

        describe('filtering errors', () => {
            let globals: HogFunctionInvocationGlobals

            beforeEach(() => {
                globals = createHogExecutionGlobals({
                    project: {
                        id: team.id,
                    } as any,
                    event: {
                        uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                        event: '$pageview',
                        properties: {
                            $current_url: 'https://posthog.com',
                            $lib_version: '1.0.0',
                        },
                    } as any,
                })
            })

            it('should filter out functions that error while filtering', async () => {
                const erroringFunction = await insertHogFunction({
                    ...HOG_EXAMPLES.input_printer,
                    ...HOG_INPUTS_EXAMPLES.secret_inputs,
                    ...HOG_FILTERS_EXAMPLES.broken_filters,
                })
                await processor.processBatch([globals])
                expect(mockProducerObserver.getProducedKafkaMessages()).toMatchObject([
                    {
                        key: expect.any(String),
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: erroringFunction.id,
                            count: 1,
                            metric_kind: 'other',
                            metric_name: 'filtering_failed',
                            team_id: 2,
                            timestamp: expect.any(String),
                        },
                    },
                    {
                        topic: 'log_entries_test',
                        value: {
                            message:
                                'Error filtering event b3a1fe86-b10c-43cc-acaf-d208977608d0: Invalid HogQL bytecode, stack is empty, can not pop',
                        },
                    },
                ])
            })
        })
    })
})
