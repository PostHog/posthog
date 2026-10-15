import { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'

import { getAsyncFunctionHandler } from '../async-function-registry'
import { CyclotronJobInvocationResult } from '../types'
import './fetch-handler'

describe('fetch handler', () => {
    const callFetch = async (
        fetchOptions: Record<string, any>,
        context: Record<string, unknown> = {}
    ): Promise<CyclotronInvocationQueueParametersFetchType> => {
        const result = { invocation: {} } as CyclotronJobInvocationResult<any>
        await getAsyncFunctionHandler('fetch')!.execute(['https://example.com', fetchOptions], context as any, result)
        return result.invocation.queueParameters as CyclotronInvocationQueueParametersFetchType
    }

    // Receivers dedupe on webhook-id, so two deliveries must never share one. A
    // single invocation can call fetch repeatedly, which anything derived from the
    // invocation would collapse into one id.
    it('gives every signed fetch call its own webhook id', async () => {
        const first = await callFetch({ standard_webhooks: { secret_input: 'signing_secret' } })
        const second = await callFetch({ standard_webhooks: { secret_input: 'signing_secret' } })

        expect(first.standard_webhooks?.secret_input).toBe('signing_secret')
        expect(first.standard_webhooks?.webhook_id).toBeTruthy()
        expect(second.standard_webhooks?.webhook_id).not.toBe(first.standard_webhooks?.webhook_id)
    })
    it('preserves a source event id across separate signed deliveries', async () => {
        const options = {
            body: { eventId: 'event-123' },
            standard_webhooks: { secret_input: 'signing_secret', webhook_id: 'event-123' },
        }
        const first = await callFetch(options)
        const second = await callFetch(options)

        expect(first.standard_webhooks?.webhook_id).toBe('event-123')
        expect(second.standard_webhooks?.webhook_id).toBe('event-123')
        expect(parseJSON(first.body!)).toEqual({ eventId: 'event-123' })
    })

    it('queues MCP lifecycle metadata and preserves the source event id', async () => {
        const id = '2de35c02-f8b8-4222-a777-cb4ac56edc13'
        const generation = '80bc1fd7-4a99-4aef-bdac-fc15f0970c3a'
        const params = await callFetch(
            {
                headers: { 'X-MCP-Subscription-Id': id },
                body: { eventId: 'event-123' },
                standard_webhooks: { secret_input: 'signing_secret' },
            },
            {
                globals: { inputs: { mcp_generation: generation } },
                invocation: {
                    hogFunction: {
                        encrypted_inputs: { mcp_credential: { value: 'phx_not_queued' } },
                        filters: { bytecode: ['_H', 1] },
                    },
                },
            }
        )
        expect(params.type).toBe('mcp_event')
        expect(params.mcp_event_subscription).toEqual({ id, generation, filter_bytecode: ['_H', 1] })
        expect(params.standard_webhooks?.webhook_id).toBe('event-123')
        expect(params).not.toHaveProperty('mcp_credential')
        expect(JSON.stringify(params)).not.toContain('phx_not_queued')
    })

    it('preserves ordinary custom MCP headers without treating them as managed destinations', async () => {
        const params = await callFetch({ headers: { 'X-MCP-Subscription-Id': 'customer-defined-id' } })
        expect(params.headers?.['X-MCP-Subscription-Id']).toBe('customer-defined-id')
        expect(params.mcp_event_subscription).toBeUndefined()
    })

    it('rejects an empty explicit webhook id', async () => {
        await expect(
            callFetch({ standard_webhooks: { secret_input: 'signing_secret', webhook_id: '' } })
        ).rejects.toThrow()
    })
})
