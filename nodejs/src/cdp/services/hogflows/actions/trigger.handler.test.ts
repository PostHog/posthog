import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow } from '~/cdp/schema/hogflow'

import { findActionByType } from '../hogflow-utils'
import { ActionHandlerResult } from './action.interface'
import { TriggerHandler } from './trigger.handler'

describe('TriggerHandler', () => {
    // properties.channel == 'C0ALERTS', as the HogQL compiler emits for a channel exact filter
    const CHANNEL_BYTECODE = ['_H', 1, 32, 'C0ALERTS', 32, 'channel', 32, 'properties', 1, 2, 11]
    // properties.status == 'churned'
    const ROW_BYTECODE = ['_H', 1, 32, 'churned', 32, 'status', 32, 'properties', 1, 2, 11]

    const run = async (
        triggerConfig: HogFlow['trigger'],
        event: { event: string; properties?: Record<string, any> }
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
        const handlerResult = await new TriggerHandler().execute({ invocation, action, result })
        return { result: handlerResult, logs: result.logs.map((log: { message: string }) => log.message) }
    }

    const slackTrigger = (filters: Record<string, any> = {}): HogFlow['trigger'] =>
        ({ type: 'slack-message', filters }) as HogFlow['trigger']

    it('skips a slack-message trigger when the test event is not $slack_message_received', async () => {
        const { result, logs } = await run(slackTrigger(), { event: '$pageview' })

        expect(result).toEqual({ finished: true, skipped: true })
        expect(logs).toEqual([
            "Slack message triggers only fire for '$slack_message_received' events. A '$pageview' event would not trigger this workflow.",
        ])
    })

    it.each([
        ['matching', 'C0ALERTS', 'exit'],
        ['non-matching', 'C0OTHER', null],
    ])(
        'evaluates slack-message trigger filters against a %s channel',
        async (_label, channel, expectedNextActionId) => {
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
        }
    )

    it('continues a slack-message trigger with no property filters when the event name matches', async () => {
        // A saved flow with no filters carries the server-compiled always-true bytecode.
        const { result } = await run(slackTrigger({ properties: [], bytecode: ['_h', 29] }), {
            event: '$slack_message_received',
        })

        expect(result.nextAction?.id).toEqual('exit')
    })

    it.each([
        ['matching', 'churned', 'exit'],
        ['non-matching', 'active', null],
    ])('evaluates warehouse-row trigger filters against a %s row', async (_label, status, expectedNextActionId) => {
        const { result } = await run(
            {
                type: 'data-warehouse-table',
                table_name: 'postgres.public.accounts',
                filters: { properties: [{ key: 'status' }], bytecode: ROW_BYTECODE },
            } as HogFlow['trigger'],
            { event: '$warehouse_source_row', properties: { status } }
        )

        if (expectedNextActionId) {
            expect(result.nextAction?.id).toEqual(expectedNextActionId)
        } else {
            expect(result).toEqual({ finished: true, skipped: true })
        }
    })

    it('continues a trigger type without filters regardless of the event', async () => {
        const { result } = await run({ type: 'schedule' } as HogFlow['trigger'], { event: '$pageview' })

        expect(result.nextAction?.id).toEqual('exit')
    })
})
