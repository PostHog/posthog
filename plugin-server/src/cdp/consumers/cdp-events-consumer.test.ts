// eslint-disable-next-line simple-import-sort/imports
import { mockProducerObserver } from '../../../tests/helpers/mocks/producer.mock'

import { HogWatcherState } from '../services/monitoring/hog-watcher.service'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../types'
import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import {
    createOrganization,
    createTeam,
    getFirstTeam,
    getTeam,
    resetTestDatabase,
    updateOrganizationAvailableFeatures,
} from '../../../tests/helpers/sql'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import {
    createHogExecutionGlobals,
    insertHogFunction as _insertHogFunction,
    createKafkaMessage,
    createIncomingEvent,
    createInternalEvent,
} from '../_tests/fixtures'
import { CdpEventsConsumer, counterMissingAddon } from './cdp-events.consumer'
import { CdpInternalEventsConsumer } from './cdp-internal-event.consumer'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { insertHogFlow as _insertHogFlow } from '../_tests/fixtures-hogflows'
import { HogFlow } from '~/schema/hogflow'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'

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
                    hogType !== 'destination'
                        ? []
                        : [
                              {
                                  key: globals.event.uuid,
                                  topic: 'clickhouse_app_metrics2_test',
                                  value: {
                                      app_source: 'cdp_destination',
                                      app_source_id: globals.event.uuid,
                                      count: 1,
                                      metric_kind: 'success',
                                      metric_name: 'event_triggered_destination',
                                      team_id: 2,
                                      timestamp: expect.any(String),
                                  },
                              },
                              {
                                  key: 'custom',
                                  topic: 'clickhouse_app_metrics2_test',
                                  value: {
                                      app_source: 'cdp_destination',
                                      app_source_id: 'custom',
                                      count: 1,
                                      metric_kind: 'success',
                                      metric_name: 'destination_invoked',
                                      instance_id: invocations[0].id,
                                      team_id: 2,
                                      timestamp: expect.any(String),
                                  },
                              },
                              {
                                  key: 'custom',
                                  topic: 'clickhouse_app_metrics2_test',
                                  value: {
                                      app_source: 'cdp_destination',
                                      app_source_id: 'custom',
                                      count: 1,
                                      metric_kind: 'success',
                                      metric_name: 'destination_invoked',
                                      instance_id: invocations[1].id,
                                      team_id: 2,
                                      timestamp: expect.any(String),
                                  },
                              },
                          ]
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
                    ...(hogType !== 'destination'
                        ? []
                        : [
                              {
                                  key: globals.event.uuid,
                                  topic: 'clickhouse_app_metrics2_test',
                                  value: {
                                      app_source: 'cdp_destination',
                                      app_source_id: globals.event.uuid,
                                      count: 1,
                                      metric_kind: 'success',
                                      metric_name: 'event_triggered_destination',
                                      team_id: 2,
                                      timestamp: expect.any(String),
                                  },
                              },
                              {
                                  key: 'custom',
                                  topic: 'clickhouse_app_metrics2_test',
                                  value: {
                                      app_source: 'cdp_destination',
                                      app_source_id: 'custom',
                                      count: 1,
                                      metric_kind: 'success',
                                      metric_name: 'destination_invoked',
                                      instance_id: invocations[0].id,
                                      team_id: 2,
                                      timestamp: expect.any(String),
                                  },
                              },
                          ]),
                ])
            })

            it.each([
                [HogWatcherState.disabledForPeriod, 'disabled_temporarily'],
                [HogWatcherState.disabledIndefinitely, 'disabled_permanently'],
            ])('should filter out functions that are disabled', async (state, metric_name) => {
                await processor.hogWatcher.forceStateChange(fnFetchNoFilters, state)
                await processor.hogWatcher.forceStateChange(fnPrinterPageviewFilters, state)

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

    describe('missing addon', () => {
        let counterMissingAddonSpy: jest.SpyInstance
        beforeEach(async () => {
            // Team 1 - has the addon
            await insertHogFunction({
                team_id: team.id,
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            await updateOrganizationAvailableFeatures(hub.postgres, team2.organization_id, [])

            // Team 2 - doesn't have the addon
            await insertHogFunction({
                team_id: team2.id,
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            counterMissingAddonSpy = jest.spyOn(counterMissingAddon, 'labels')
        })
        it('should process events for teams with the addon', async () => {
            if (processor instanceof CdpInternalEventsConsumer) {
                return
            }
            const { invocations } = await processor.processBatch([
                createHogExecutionGlobals({
                    project: {
                        id: team.id,
                    } as any,
                }),
            ])
            expect(invocations).toHaveLength(1)
            expect(invocations[0].teamId).toBe(team.id)
            expect(counterMissingAddonSpy).not.toHaveBeenCalled()
        })

        it('should not process events for teams without the addon', async () => {
            if (processor instanceof CdpInternalEventsConsumer) {
                return
            }
            const { invocations } = await processor.processBatch([
                createHogExecutionGlobals({
                    project: {
                        id: team2.id,
                    } as any,
                }),
            ])
            expect(counterMissingAddonSpy).toHaveBeenCalledWith({ team_id: team2.id })
            // TODO: Swap this to 0 once we release it
            expect(invocations).toHaveLength(1)
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
            await insertHogFlow(new FixtureHogFlowBuilder().withTeamId(team.id).build())

            const invocations = await processor['createHogFlowInvocations']([globals])
            expect(invocations).toHaveLength(0)
        })

        it('should create hog flow invocations with matching filters', async () => {
            const hogFlow = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withTrigger({
                        type: 'event',
                        filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
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
                    personId: 'uuid',
                    variables: {},
                },
                teamId: 2,
            })
        })
    })
})
