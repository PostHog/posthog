import type { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { internalFetch } from '~/common/utils/request'

import type { CyclotronJobInvocationHogFunction } from '../types'
import { prepareMcpEventDelivery } from './mcp-event-delivery'

jest.mock('~/common/utils/request', () => ({ internalFetch: jest.fn() }))

describe('MCP event delivery authorization', () => {
    const invocation = {
        teamId: 123,
        hogFunction: {
            id: 'eae89749-3d0c-4ddb-875a-04771a7b9e34',
            inputs: {},
            encrypted_inputs: { mcp_credential: { value: 'fake-user-credential' } },
        },
    } as unknown as CyclotronJobInvocationHogFunction
    const params: CyclotronInvocationQueueParametersFetchType = {
        type: 'fetch',
        url: 'https://example.com/callback',
        method: 'POST',
        body: '{"eventId":"sample-event"}',
        mcp_event_subscription: {
            id: 'b69e52cb-f4de-47dc-95ae-60801343439b',
            generation: 'fe1d8590-2d5c-42c3-99d2-707653293785',
        },
    }

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('uses the caller credential and returns the authorized body and fresh signature', async () => {
        const authorized = {
            body: '{"eventId":"sample-event","data":{}}',
            headers: { 'webhook-signature': 'v1,fake-signature' },
        }
        jest.mocked(internalFetch).mockResolvedValue({
            status: 200,
            text: jest.fn().mockResolvedValue(JSON.stringify(authorized)),
        } as any)

        const result = await prepareMcpEventDelivery({ invocation, params, internalApiBaseUrl: 'http://web:8000' })
        expect(result).toEqual({ ok: true, ...authorized })
        expect(internalFetch).toHaveBeenCalledWith(
            expect.stringContaining('/api/projects/123/mcp_event_subscriptions/'),
            expect.objectContaining({
                headers: { 'Content-Type': 'application/json', Authorization: 'Bearer fake-user-credential' },
                body: JSON.stringify({
                    generation: params.mcp_event_subscription!.generation,
                    function_id: invocation.hogFunction.id,
                    url: params.url,
                    body: params.body,
                }),
            })
        )
        expect(JSON.stringify(params)).not.toContain('fake-user-credential')
    })

    it.each([
        [401, 410],
        [403, 410],
        [404, 410],
        [400, 400],
        [429, 503],
        [500, 503],
        [503, 503],
    ])('maps authorization status %s to delivery status %s', async (status, expected) => {
        jest.mocked(internalFetch).mockResolvedValue({ status, dump: jest.fn().mockResolvedValue(undefined) } as any)
        expect(await prepareMcpEventDelivery({ invocation, params, internalApiBaseUrl: 'http://web:8000' })).toEqual({
            ok: false,
            status: expected,
        })
    })

    it('fails closed on an unreachable or malformed authorization response', async () => {
        jest.mocked(internalFetch).mockRejectedValue(new Error('unavailable'))
        expect(await prepareMcpEventDelivery({ invocation, params, internalApiBaseUrl: 'http://web:8000' })).toEqual({
            ok: false,
            status: 503,
        })
        jest.mocked(internalFetch).mockResolvedValue({ status: 200, text: jest.fn().mockResolvedValue('{}') } as any)
        expect(await prepareMcpEventDelivery({ invocation, params, internalApiBaseUrl: 'http://web:8000' })).toEqual({
            ok: false,
            status: 503,
        })
    })
})
