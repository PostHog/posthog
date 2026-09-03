import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow } from '~/cdp/schema/hogflow'

import { findActionByType } from '../hogflow-utils'
import { ActionHandlerResult } from './action.interface'
import { SlackAppLookup, TriggerHandler } from './trigger.handler'

describe('TriggerHandler', () => {
    // properties.channel == 'C0ALERTS', as the HogQL compiler emits for a channel exact filter
    const CHANNEL_BYTECODE = ['_H', 1, 32, 'C0ALERTS', 32, 'channel', 32, 'properties', 1, 2, 11]
    // properties.status == 'churned'
    const ROW_BYTECODE = ['_H', 1, 32, 'churned', 32, 'status', 32, 'properties', 1, 2, 11]

    // Maps integration id -> the team and app_id stored on that integration, mirroring what
    // IntegrationManagerService.getMany returns (a lookup with no team scoping of its own).
    // Empty by default, so no event looks self-sent unless a test names it. teamId defaults to
    // 1, the fixture hogflow's own team - set it explicitly to simulate another team's row.
    const fakeIntegrationLookup = (apps: Record<number, { appId: string; teamId?: number }> = {}): SlackAppLookup => ({
        getMany: (ids) =>
            Promise.resolve(
                Object.fromEntries(
                    ids.map((id) => [
                        id,
                        id in apps ? { team_id: apps[id].teamId ?? 1, config: { app_id: apps[id].appId } } : null,
                    ])
                )
            ),
    })

    const run = async (
        triggerConfig: HogFlow['trigger'],
        event: { event: string; properties?: Record<string, any> },
        integrationLookup: SlackAppLookup = fakeIntegrationLookup()
    ): Promise<{ result: ActionHandlerResult; logs: string[] }> => {
        const hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    trigger: { type: 'trigger', config: triggerConfig as any },
                    exit: { type: 'exit', config: {} },
                },
                edges: [{ from: 'trigger', to: 'exit', type: 'continue' }],
            })
            .build()
        const action = findActionByType(hogFlow, 'trigger')!
        const invocation = createExampleHogFlowInvocation(hogFlow, { event: event as any })
        invocation.state.currentAction = { id: action.id, startedAtTimestamp: Date.now() }

        const result = { logs: [] } as any
        const handlerResult = await new TriggerHandler(integrationLookup).execute({ invocation, action, result })
        return { result: handlerResult, logs: result.logs.map((log: { message: string }) => log.message) }
    }

    const slackTrigger = (filters: Record<string, any> = {}): HogFlow['trigger'] =>
        ({
            type: 'internal-event',
            filters: {
                source: 'internal-events',
                events: [{ id: '$slack_message_received', type: 'events' }],
                ...filters,
            },
        }) as HogFlow['trigger']

    it('skips an internal-event trigger when the test event is not one its filters name', async () => {
        const { result, logs } = await run(slackTrigger(), { event: '$pageview' })

        expect(result).toEqual({ finished: true, skipped: true })
        expect(logs).toEqual([
            "This workflow triggers on '$slack_message_received' events. A '$pageview' event would not trigger this workflow.",
        ])
    })

    it('skips an internal-event trigger whose filters name no events', async () => {
        // The consumer's eligibility check never fires such a trigger, so a test run must not
        // pass it either, even though its property filters alone would match anything.
        const { result, logs } = await run(
            { type: 'internal-event', filters: { source: 'internal-events', events: [] } } as any,
            { event: '$slack_message_received' }
        )

        expect(result).toEqual({ finished: true, skipped: true })
        expect(logs).toEqual([
            "This trigger's filters do not name any internal events, so no event would trigger this workflow.",
        ])
    })

    it("skips an internal-event trigger for PostHog's own GitHub App activity", async () => {
        const { result, logs } = await run(
            {
                type: 'internal-event',
                filters: {
                    source: 'internal-events',
                    events: [{ id: '$github_event_received', type: 'events' }],
                    properties: [],
                    bytecode: ['_h', 29],
                },
            } as any,
            { event: '$github_event_received', properties: { own_app: true } }
        )

        expect(result).toEqual({ finished: true, skipped: true })
        expect(logs).toEqual(["Activity from PostHog's own GitHub App would not trigger this workflow."])
    })

    it.each([
        ['matching', 'C0ALERTS', 'exit'],
        ['non-matching', 'C0OTHER', null],
    ])('evaluates the trigger property filters against a %s channel', async (_label, channel, expectedNextActionId) => {
        const { result, logs } = await run(
            slackTrigger({ properties: [{ key: 'channel' }], bytecode: CHANNEL_BYTECODE }),
            { event: '$slack_message_received', properties: { channel } }
        )

        if (expectedNextActionId) {
            expect(result.nextAction?.id).toEqual(expectedNextActionId)
        } else {
            expect(result).toEqual({ finished: true, skipped: true })
            expect(logs).toEqual(['Workflow trigger did not match the event.'])
        }
    })

    it('continues an internal-event trigger with no property filters when the event name matches', async () => {
        // A saved flow with no filters carries the server-compiled always-true bytecode.
        const { result } = await run(slackTrigger({ properties: [], bytecode: ['_h', 29] }), {
            event: '$slack_message_received',
        })

        expect(result.nextAction?.id).toEqual('exit')
    })

    it("skips a Slack-triggered workflow for a message PostHog's own connected app posted", async () => {
        const { result, logs } = await run(
            slackTrigger({ properties: [], bytecode: ['_h', 29] }),
            { event: '$slack_message_received', properties: { integration_id: 1, app_id: 'A_OWN_APP' } },
            fakeIntegrationLookup({ 1: { appId: 'A_OWN_APP' } })
        )

        expect(result).toEqual({ finished: true, skipped: true })
        expect(logs).toEqual(["Messages PostHog's own connected Slack app posted would not trigger this workflow."])
    })

    it('continues a Slack-triggered workflow for a message from a different Slack app', async () => {
        const { result } = await run(
            slackTrigger({ properties: [], bytecode: ['_h', 29] }),
            { event: '$slack_message_received', properties: { integration_id: 1, app_id: 'A_OTHER_APP' } },
            fakeIntegrationLookup({ 1: { appId: 'A_OWN_APP' } })
        )

        expect(result.nextAction?.id).toEqual('exit')
    })

    it("does not treat another team's integration as this workflow's own app, even on an app_id match", async () => {
        // integration_id and app_id come straight from the test-run payload, and getMany resolves
        // an id across all teams. Without a team_id check, this is a cross-team oracle: a test
        // run on any workflow can confirm another team's integration_id -> app_id pairing.
        const { result } = await run(
            slackTrigger({ properties: [], bytecode: ['_h', 29] }),
            { event: '$slack_message_received', properties: { integration_id: 1, app_id: 'A_OWN_APP' } },
            fakeIntegrationLookup({ 1: { appId: 'A_OWN_APP', teamId: 999 } })
        )

        expect(result.nextAction?.id).toEqual('exit')
    })

    // A saved trigger with no row filters carries the server-compiled always-true bytecode.
    const NO_FILTERS_BYTECODE = ['_h', 29]

    const warehouseTableTrigger = (
        filters: Record<string, any> = { properties: [], bytecode: NO_FILTERS_BYTECODE }
    ): HogFlow['trigger'] =>
        ({
            type: 'data-warehouse-table',
            table_name: 'postgres.public.accounts',
            filters,
        }) as HogFlow['trigger']

    it.each([
        ['matching', 'churned', 'exit'],
        ['non-matching', 'active', null],
    ])('evaluates warehouse-row trigger filters against a %s row', async (_label, status, expectedNextActionId) => {
        const { result } = await run(
            warehouseTableTrigger({ properties: [{ key: 'status' }], bytecode: ROW_BYTECODE }),
            { event: '$warehouse_source_row', properties: { status, $source_table: 'postgres.public.accounts' } }
        )

        if (expectedNextActionId) {
            expect(result.nextAction?.id).toEqual(expectedNextActionId)
        } else {
            expect(result).toEqual({ finished: true, skipped: true })
        }
    })

    // A freshly created warehouse trigger has empty filters, which match unconditionally - so
    // without a row-kind/table check any event would otherwise pass it, the same false positive
    // this handler already closes for internal-event triggers.
    it.each([
        ['a non-warehouse event', '$pageview', {}],
        ['the wrong row kind', '$warehouse_view_row', { $source_table: 'postgres.public.accounts' }],
        ['a row from another table', '$warehouse_source_row', { $source_table: 'postgres.public.orders' }],
    ])('skips a data-warehouse-table trigger with no filters given %s', async (_label, eventName, properties) => {
        const { result } = await run(warehouseTableTrigger(), { event: eventName, properties })

        expect(result).toEqual({ finished: true, skipped: true })
    })

    it('continues a data-warehouse-view trigger given a matching view row', async () => {
        const { result } = await run(
            {
                type: 'data-warehouse-view',
                table_name: 'materialized_active_users',
                filters: { properties: [], bytecode: NO_FILTERS_BYTECODE },
            } as HogFlow['trigger'],
            { event: '$warehouse_view_row', properties: { $source_table: 'materialized_active_users' } }
        )

        expect(result.nextAction?.id).toEqual('exit')
    })

    it('continues a trigger type without filters regardless of the event', async () => {
        const { result } = await run({ type: 'schedule' } as HogFlow['trigger'], { event: '$pageview' })

        expect(result.nextAction?.id).toEqual('exit')
    })
})
