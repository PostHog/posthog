import type { AsyncFunctionContext } from '../async-function-registry'
import { getAsyncFunctionHandler } from '../async-function-registry'
import type { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import './fetch-handler'
import './mcp-event-handler'

describe('MCP event handler', () => {
    const subscription = {
        id: 'b69e52cb-f4de-47dc-95ae-60801343439b',
        generation: 'fe1d8590-2d5c-42c3-99d2-707653293785',
        filter_bytecode: ['_H', 1],
    }
    const context = {
        invocation: {
            state: { mcpEvent: { filterBytecode: subscription.filter_bytecode } },
            hogFunction: {
                encrypted_inputs: { mcp_credential: { value: 'fake-user-credential' } },
                filters: { bytecode: subscription.filter_bytecode },
            },
        },
        globals: { inputs: { mcp_subscription_id: subscription.id, mcp_generation: subscription.generation } },
    } as unknown as AsyncFunctionContext

    it('queues explicit subscription identity without copying the credential', async () => {
        const result = { invocation: {} } as CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
        await getAsyncFunctionHandler('mcpEventFetch')!.execute(
            ['https://example.com/callback', { eventId: 'sample-event' }],
            context,
            result
        )
        expect(result.invocation.queueParameters).toEqual({
            type: 'mcp_event',
            url: 'https://example.com/callback',
            body: '{"eventId":"sample-event"}',
            mcp_event_subscription: { id: subscription.id, generation: subscription.generation },
        })
        expect(JSON.stringify(result.invocation.queueParameters)).not.toContain('fake-user-credential')
    })

    it('keeps an ordinary fetch ordinary even when the invocation has managed inputs', async () => {
        const result = { invocation: {} } as CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
        await getAsyncFunctionHandler('fetch')!.execute(
            ['https://example.com/callback', { headers: { 'X-MCP-Subscription-Id': subscription.id } }],
            context,
            result
        )
        expect(result.invocation.queueParameters?.type).toBe('fetch')
        expect(result.invocation.queueParameters).not.toHaveProperty('mcp_event_subscription')
    })

    it.each(['credential', 'snapshot'])('rejects a reserved send without its %s', (missing) => {
        const result = { invocation: {} } as CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
        const unmanaged = {
            ...context,
            invocation: {
                ...context.invocation,
                hogFunction: {
                    ...context.invocation.hogFunction,
                    encrypted_inputs: missing === 'credential' ? {} : context.invocation.hogFunction.encrypted_inputs,
                },
                state: {
                    ...context.invocation.state,
                    mcpEvent: missing === 'snapshot' ? undefined : context.invocation.state.mcpEvent,
                },
            },
        }
        expect(() => getAsyncFunctionHandler('mcpEventFetch')!.execute([], unmanaged, result)).toThrow(
            missing === 'credential' ? 'requires a managed subscription' : 'requires the matched filter snapshot'
        )
        expect(result.invocation.queueParameters).toBeUndefined()
    })
})
