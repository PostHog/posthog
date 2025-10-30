import { mockProducerObserver } from '../../../tests/helpers/mocks/producer.mock'

import { HogFlow } from '~/schema/hogflow'

import { createOrganization, createTeam, getFirstTeam, getTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import {
    insertHogFunction as _insertHogFunction,
    createHogExecutionGlobals,
    createIncomingEvent,
    createInternalEvent,
    createKafkaMessage,
} from '../_tests/fixtures'
import { insertHogFlow as _insertHogFlow } from '../_tests/fixtures-hogflows'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { HogWatcherState } from '../services/monitoring/hog-watcher.service'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../types'
import { CdpEventsConsumer } from './cdp-events.consumer'
import { CdpInternalEventsConsumer } from './cdp-internal-event.consumer'

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
        const otherOrganizationId = await createOrganization(hub.postgres)
        const team2Id = await createTeam(hub.postgres, otherOrganizationId)
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
                    state: {
                        globals: {
                            event: globals.event,
                        },
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

            it('should log correct metrics', async () => {
                const { invocations } = await processor.processBatch([globals])

                expect(invocations).toHaveLength(2)
                expect(invocations).toMatchObject([
                    matchInvocation(fnFetchNoFilters, globals),
                    matchInvocation(fnPrinterPageviewFilters, globals),
                ])

                expect(mockQueueInvocations).toHaveBeenCalledWith(invocations)

                expect(
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_app_metrics2_test')
                ).toMatchObject(
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
                                team_id: 2,
                                timestamp: expect.any(String),
                            },
                        },
                        hogType === 'destination' && {
                            key: expect.any(String),
                            topic: 'clickhouse_app_metrics2_test',
                            value: {
                                app_source: 'hog_function',
                                app_source_id: fnFetchNoFilters.id,
                                count: 1,
                                metric_kind: 'billing',
                                metric_name: 'billable_invocation',
                                team_id: 2,
                                timestamp: expect.any(String),
                            },
                        },
                        {
                            key: expect.any(String),
                            topic: 'clickhouse_app_metrics2_test',
                            value: {
                                app_source: 'hog_function',
                                app_source_id: fnPrinterPageviewFilters.id,
                                count: 1,
                                metric_kind: 'other',
                                metric_name: 'triggered',
                                team_id: 2,
                                timestamp: expect.any(String),
                            },
                        },
                        hogType === 'destination' && {
                            key: expect.any(String),
                            topic: 'clickhouse_app_metrics2_test',
                            value: {
                                app_source: 'hog_function',
                                app_source_id: fnPrinterPageviewFilters.id,
                                count: 1,
                                metric_kind: 'billing',
                                metric_name: 'billable_invocation',
                                team_id: 2,
                                timestamp: expect.any(String),
                            },
                        },
                    ].filter((x) => !!x)
                )
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
                    {
                        key: expect.any(String),
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: fnFetchNoFilters.id,
                            count: 1,
                            metric_kind: 'other',
                            metric_name: 'triggered',
                            team_id: 2,
                            timestamp: expect.any(String),
                        },
                    },
                    ...(hogType !== 'destination'
                        ? []
                        : [
                              {
                                  key: expect.any(String),
                                  topic: 'clickhouse_app_metrics2_test',
                                  value: {
                                      app_source: 'hog_function',
                                      app_source_id: fnFetchNoFilters.id,
                                      count: 1,
                                      metric_kind: 'billing',
                                      metric_name: 'billable_invocation',
                                      team_id: 2,
                                      timestamp: expect.any(String),
                                  },
                              },
                          ]),
                ])
            })

            it('should filter out functions that are disabled', async () => {
                await processor.hogWatcher.forceStateChange(fnFetchNoFilters, HogWatcherState.disabled)
                await processor.hogWatcher.forceStateChange(fnPrinterPageviewFilters, HogWatcherState.disabled)

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
                            metric_name: 'disabled_permanently',
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
                            metric_name: 'disabled_permanently',
                            team_id: 2,
                        },
                    },
                ])
            })

            it('should execute simple event-matcher bytecode', async () => {
                // Insert a function that uses the provided bytecode (event == "$exception")
                const fnEventMatcher = await insertHogFunction({
                    ...HOG_EXAMPLES.input_printer,
                    ...HOG_INPUTS_EXAMPLES.secret_inputs,
                    filters: {
                        events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }],
                        actions: [],
                        bytecode: ['_H', 1, 32, '$pageview', 32, 'event', 1, 1, 11],
                    },
                })

                const { invocations } = await processor.processBatch([globals])

                // This bytecode matches $exception, while the event is $pageview, so it should not add an invocation
                expect(invocations).toHaveLength(3)
                expect(invocations).toMatchObject([
                    matchInvocation(fnFetchNoFilters, globals),
                    matchInvocation(fnPrinterPageviewFilters, globals),
                    matchInvocation(fnEventMatcher, globals),
                ])

                // Verify jobs enqueued
                expect(mockQueueInvocations).toHaveBeenCalledWith(invocations)
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

describe('hog flow processing', () => {
    let processor: CdpEventsConsumer | CdpInternalEventsConsumer
    let hub: Hub
    let team: Team

    const insertHogFlow = async (hogFlow: HogFlow) => {
        const teamId = hogFlow.team_id ?? team.id

        const item = await _insertHogFlow(hub.postgres, hogFlow)
        // Trigger the reload that django would do
        processor['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [item.id])
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        processor = new CdpEventsConsumer(hub)

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
        } as unknown as jest.Mocked<CyclotronJobQueue>

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

    describe('createHogFlowInvocations', () => {
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

        it('should not create hog flow invocations with no filters', async () => {
            const hogFlow = new FixtureHogFlowBuilder().withTeamId(team.id).build()
            hogFlow.trigger = {} as any
            await insertHogFlow(hogFlow)

            const invocations = await processor['createHogFlowInvocations']([globals])
            expect(invocations).toHaveLength(0)
        })

        it('should not create hog flow invocations with webhook triggers', async () => {
            const hogFlow = new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withSimpleWorkflow({
                    trigger: {
                        type: 'webhook',
                        template_id: 'test',
                        inputs: {},
                    },
                })
                .build()
            await insertHogFlow(hogFlow)

            const invocations = await processor['createHogFlowInvocations']([globals])
            expect(invocations).toHaveLength(0)
        })

        it('should create hog flow invocations with matching filters', async () => {
            const hogFlow = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'event',
                            filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters ?? {},
                        },
                    })
                    .build()
            )

            const noInvocations = await processor['createHogFlowInvocations']([
                {
                    ...globals,
                    event: {
                        ...globals.event,
                        event: 'not-a-pageview',
                    },
                },
            ])

            expect(noInvocations).toHaveLength(0)

            const invocations = await processor['createHogFlowInvocations']([globals])
            expect(invocations).toHaveLength(1)
            expect(invocations[0]).toMatchObject({
                functionId: hogFlow.id,
                hogFlow: {
                    id: hogFlow.id,
                },
                id: expect.any(String),
                queue: 'hogflow',
                queuePriority: 1,
                state: {
                    event: globals.event,
                    actionStepCount: 0,
                },
                teamId: 2,
            })
        })
    })
})
