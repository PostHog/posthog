import { createMockJobQueue } from '../../../tests/helpers/mocks/job-queue.mock'
import '../../../tests/helpers/mocks/producer.mock'

import { HogFlow } from '~/cdp/schema/hogflow'
import { closeHub, createHub } from '~/common/utils/db/hub'

import { createCdpConsumerDeps } from '../../../tests/helpers/cdp'
import { createOrganization, createTeam, getFirstTeam, getTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, Team } from '../../types'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import {
    insertHogFunction as _insertHogFunction,
    createInternalEvent,
    createKafkaMessage,
    insertIntegration,
} from '../_tests/fixtures'
import { insertHogFlow as _insertHogFlow } from '../_tests/fixtures-hogflows'
import { HogWatcherState } from '../services/monitoring/hog-watcher.service'
import { HogFunctionType } from '../types'
import { CdpInternalEventsConsumer } from './cdp-internal-event.consumer'

describe('CDP Internal Events Consumer', () => {
    let processor: CdpInternalEventsConsumer
    let hub: Hub
    let team: Team
    let team2: Team
    let mockQueueInvocations: jest.MockedFunction<any>

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const teamId = hogFunction.team_id ?? team.id
        const item = await _insertHogFunction(hub.postgres, teamId, {
            ...hogFunction,
            type: 'internal_destination',
        })
        // Trigger the reload that django would do
        processor['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [item.id])
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({
            SITE_URL: 'http://localhost:8000',
        })
        team = await getFirstTeam(hub.postgres)

        const otherOrganizationId = await createOrganization(hub.postgres)
        const team2Id = await createTeam(hub.postgres, otherOrganizationId)
        team2 = (await getTeam(hub.postgres, team2Id))!

        jest.spyOn(hub.quotaLimiting, 'isTeamQuotaLimited').mockResolvedValue(false)

        const mockJobQueue = createMockJobQueue()
        processor = new CdpInternalEventsConsumer(hub, createCdpConsumerDeps(hub), {
            hogQueue: mockJobQueue,
            hogflowQueue: mockJobQueue,
        })

        // Don't actually connect Kafka — test the core logic only
        processor['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(),
        } as any

        mockQueueInvocations = mockJobQueue.queueInvocations

        await processor.start()
    })

    afterEach(async () => {
        await processor.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('_parseKafkaBatch', () => {
        it('should ignore invalid message', async () => {
            const events = await processor._parseKafkaBatch([createKafkaMessage({})])
            expect(events).toHaveLength(0)
        })

        it('should ignore message with no team', async () => {
            const events = await processor._parseKafkaBatch([createKafkaMessage(createInternalEvent(999999, {}))])
            expect(events).toHaveLength(0)
        })

        describe('with an existing team and hog function', () => {
            beforeEach(async () => {
                await insertHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.no_filters,
                })
            })

            it('should ignore invalid payloads', async () => {
                const events = await processor._parseKafkaBatch([
                    createKafkaMessage(
                        createInternalEvent(team.id, {
                            event: 'WRONG' as any,
                        })
                    ),
                ])
                expect(events).toHaveLength(0)
            })

            it('should parse a valid message with an existing team and hog function ', async () => {
                const event = createInternalEvent(team.id, {})
                event.event.timestamp = '2024-12-18T15:06:23.545Z'
                event.event.uuid = 'b6da2f33-ba54-4550-9773-50d3278ad61f'

                const events = await processor._parseKafkaBatch([createKafkaMessage(event)])
                expect(events).toHaveLength(1)
                expect(events[0]).toEqual({
                    event: {
                        distinct_id: 'distinct_id',
                        elements_chain: '',
                        event: '$pageview',
                        captured_at: null,
                        properties: {},
                        timestamp: '2024-12-18T15:06:23.545Z',
                        url: '',
                        uuid: 'b6da2f33-ba54-4550-9773-50d3278ad61f',
                    },
                    person: undefined,
                    project: {
                        id: 2,
                        name: 'TEST PROJECT',
                        url: 'http://localhost:8000/project/2',
                    },
                })
            })
        })
    })

    describe('team filtering', () => {
        it('should not parse events for teams without hog functions', async () => {
            await insertHogFunction({
                team_id: team.id,
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const events = [
                createKafkaMessage(createInternalEvent(team.id, {})),
                createKafkaMessage(createInternalEvent(team2.id, {})),
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

    describe('processBatch', () => {
        it('should build invocations from internal events and queue them', async () => {
            const fn = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const messages = [createKafkaMessage(createInternalEvent(team.id, {}))]
            const globals = await processor._parseKafkaBatch(messages)
            const { invocations, backgroundTask } = await processor.processBatch(globals)
            await backgroundTask

            expect(invocations).toHaveLength(1)
            expect(invocations[0].functionId).toBe(fn.id)
            expect(mockQueueInvocations).toHaveBeenCalledWith(invocations)
        })

        it('should return empty when given no events', async () => {
            const { invocations, backgroundTask } = await processor.processBatch([])
            await backgroundTask

            expect(invocations).toHaveLength(0)
            expect(mockQueueInvocations).not.toHaveBeenCalled()
        })

        it('should filter out functions that are disabled', async () => {
            const fn = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })
            await processor.hogWatcher.forceStateChange(fn, HogWatcherState.disabled)

            const messages = [createKafkaMessage(createInternalEvent(team.id, {}))]
            const globals = await processor._parseKafkaBatch(messages)
            const { invocations } = await processor.processBatch(globals)

            expect(invocations).toHaveLength(0)
        })

        it('should only load internal_destination hog functions (filters out destination type)', async () => {
            // Insert a `destination` type function for the same team
            await _insertHogFunction(hub.postgres, team.id, {
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
                type: 'destination',
            })

            // Insert an internal_destination function — should be the only one picked up
            const internalFn = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const messages = [createKafkaMessage(createInternalEvent(team.id, {}))]
            const globals = await processor._parseKafkaBatch(messages)
            const { invocations } = await processor.processBatch(globals)

            expect(invocations).toHaveLength(1)
            expect(invocations[0].functionId).toBe(internalFn.id)
        })

        it.each([
            '$billing_alert_firing',
            '$billing_alert_resolved',
            '$billing_alert_errored',
            '$billing_alert_auto_disabled',
            '$logs_alert_firing',
            '$logs_alert_resolved',
            '$logs_alert_errored',
            '$logs_alert_auto_disabled',
        ])('routes %s only to the destination matching the event and alert id', async (managedAlertEvent) => {
            const filters = (eventId: string, alertId: string) => ({
                filters: {
                    ...HOG_FILTERS_EXAMPLES.no_filters.filters,
                    events: [{ id: eventId, type: 'events' as const }],
                    properties: [{ key: 'alert_id', value: alertId, operator: 'exact', type: 'event' }],
                },
            })
            const matching = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...filters(managedAlertEvent, 'alert-1'),
            })
            await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...filters(managedAlertEvent, 'alert-2'),
            })
            const otherManagedAlertEvent =
                managedAlertEvent === '$billing_alert_firing' ? '$logs_alert_firing' : '$billing_alert_firing'
            await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...filters(otherManagedAlertEvent, 'alert-1'),
            })
            await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })
            const event = createInternalEvent(team.id, {})
            event.event.event = managedAlertEvent
            event.event.properties = { alert_id: 'alert-1', current_value: '100' }

            const globals = await processor._parseKafkaBatch([createKafkaMessage(event)])
            const { invocations } = await processor.processBatch(globals)

            expect(invocations.map((invocation) => invocation.functionId)).toEqual([matching.id])
        })

        it('invokes a legacy $insight_alert_firing destination that has no alert_id filter', async () => {
            const fn = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                filters: {
                    ...HOG_FILTERS_EXAMPLES.no_filters.filters,
                    events: [{ id: '$insight_alert_firing', type: 'events' as const }],
                },
            })
            const event = createInternalEvent(team.id, {})
            event.event.event = '$insight_alert_firing'

            const globals = await processor._parseKafkaBatch([createKafkaMessage(event)])
            const { invocations } = await processor.processBatch(globals)

            expect(invocations.map((invocation) => invocation.functionId)).toEqual([fn.id])
        })
    })

    describe('hog flow invocations', () => {
        const buildHogFlow = (teamId: number, trigger: any): HogFlow =>
            new FixtureHogFlowBuilder()
                .withTeamId(teamId)
                // Always-true bytecode (return true), so the test is about eligibility, not filters
                .withSimpleWorkflow({ trigger: { ...trigger, filters: { properties: [], bytecode: ['_h', 29] } } })
                .build()

        const slackMessage = (teamId: number, properties: Record<string, any> = {}) =>
            createInternalEvent(teamId, {
                event: {
                    timestamp: '2026-08-17T12:00:00.000Z',
                    uuid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                    event: '$slack_message_received',
                    distinct_id: 'U123',
                    properties: { channel: 'C0ALERTS', text: 'database is on fire', ...properties },
                },
            })

        it('should start a workflow whose trigger is a slack message', async () => {
            const hogFlow = await _insertHogFlow(hub.postgres, buildHogFlow(team.id, { type: 'slack-message' }))

            const globals = await processor._parseKafkaBatch([createKafkaMessage(slackMessage(team.id))])
            expect(globals).toHaveLength(1)

            const { invocations } = await processor.processBatch(globals)
            const hogFlowInvocations = invocations.filter((i: any) => i.hogFlow)
            expect(hogFlowInvocations).toHaveLength(1)
            expect(hogFlowInvocations[0].functionId).toBe(hogFlow.id)
        })

        it('should not start a slack workflow from another signal on this topic', async () => {
            // Eligibility has to match the event as well as the trigger type. Error tracking, alerts
            // and activity logs all arrive here, and a workflow whose stored filters are empty (which
            // the API accepts) matches whatever it is handed — so trigger type alone fires on all of
            // them, with no channel or ts for a reply step to use.
            await _insertHogFlow(hub.postgres, buildHogFlow(team.id, { type: 'slack-message' }))

            const globals = await processor._parseKafkaBatch([
                createKafkaMessage(
                    createInternalEvent(team.id, {
                        event: {
                            timestamp: '2026-08-17T12:00:00.000Z',
                            uuid: 'aaaaaaaa-bbbb-cccc-dddd-ffffffffffff',
                            event: '$insight_alert_firing',
                            distinct_id: 'U123',
                            properties: { alert_id: 'abc' },
                        },
                    })
                ),
            ])
            const { invocations } = await processor.processBatch(globals)

            expect(invocations.filter((i: any) => i.hogFlow)).toHaveLength(0)
        })

        it('should not start an event-triggered workflow', async () => {
            // Internal events share this topic with error tracking and activity log signals. An
            // event-triggered workflow expects those from analytics capture, so widening eligibility
            // to 'event' would fire every one of them.
            await _insertHogFlow(hub.postgres, buildHogFlow(team.id, { type: 'event' }))

            const globals = await processor._parseKafkaBatch([createKafkaMessage(slackMessage(team.id))])
            const { invocations } = await processor.processBatch(globals)

            expect(invocations.filter((i: any) => i.hogFlow)).toHaveLength(0)
        })

        it.each([
            ['PostHog posted the message', 'A0POSTHOG', 0],
            ['another app posted the message', 'A0OTHER', 1],
        ])('starts a workflow only when it did not post the message: %s', async (_name, appId, expected) => {
            // A workflow that replies in Slack sees its own reply arrive back on this topic. The
            // guard is part of eligibility, not the trigger's stored filters, so a workflow created
            // through the API or MCP still has it.
            const integration = await insertIntegration(hub.postgres, team.id, {
                kind: 'slack',
                config: { app_id: 'A0POSTHOG' },
            })
            await _insertHogFlow(hub.postgres, buildHogFlow(team.id, { type: 'slack-message' }))

            const globals = await processor._parseKafkaBatch([
                createKafkaMessage(slackMessage(team.id, { app_id: appId, integration_id: integration.id })),
            ])
            const { invocations } = await processor.processBatch(globals)

            expect(invocations.filter((i: any) => i.hogFlow)).toHaveLength(expected)
        })

        it('should parse a message for a team that has a hog flow but no hog functions', async () => {
            // The parse step used to drop any team with no internal_destination functions, which
            // would discard the event before the flow pipeline ever saw it.
            await _insertHogFlow(hub.postgres, buildHogFlow(team.id, { type: 'slack-message' }))

            const globals = await processor._parseKafkaBatch([createKafkaMessage(slackMessage(team.id))])

            expect(globals).toHaveLength(1)
        })
    })
})
