import type { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { logger } from '~/common/utils/logger'
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
        type: 'mcp_event',
        url: 'https://example.com/callback',
        method: 'POST',
        body: '{"eventId":"sample-event"}',
        mcp_event_subscription: {
            id: 'b69e52cb-f4de-47dc-95ae-60801343439b',
            generation: 'fe1d8590-2d5c-42c3-99d2-707653293785',
            filter_bytecode: ['_H', 1],
        },
    }

    beforeEach(() => {
        jest.clearAllMocks()
        jest.spyOn(logger, 'warn').mockImplementation(() => {})
    })

    afterEach(() => {
        jest.restoreAllMocks()
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
                    filter_bytecode: params.mcp_event_subscription!.filter_bytecode,
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

    it.each(['45', new Date(Date.now() + 45_000).toUTCString()])('preserves Retry-After %s', async (retryAfter) => {
        jest.mocked(internalFetch).mockResolvedValue({
            status: 429,
            headers: { 'retry-after': retryAfter },
            dump: jest.fn(),
        } as any)
        const result = await prepareMcpEventDelivery({ invocation, params, internalApiBaseUrl: 'http://web:8000' })
        expect(result).toMatchObject({ ok: false, status: 503 })
        if (!result.ok) {
            expect(result.retryAfterMs).toBeGreaterThan(40_000)
            expect(result.retryAfterMs).toBeLessThanOrEqual(45_000)
        }
    })

    it.each([
        ['dns', Object.assign(new Error('private diagnostic'), { code: 'ENOTFOUND' })],
        [
            'connection',
            new Error('private diagnostic', {
                cause: Object.assign(new Error('private cause'), { code: 'ECONNRESET' }),
            }),
        ],
        ['timeout', Object.assign(new Error('private diagnostic'), { name: 'TimeoutError' })],
        ['network', new Error('private diagnostic')],
    ])('records sanitized %s context for an unreachable authorization service', async (category, error) => {
        jest.mocked(internalFetch).mockRejectedValue(error)
        expect(await prepareMcpEventDelivery({ invocation, params, internalApiBaseUrl: 'http://web:8000' })).toEqual({
            ok: false,
            status: 503,
        })
        expect(logger.warn).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                category,
                teamId: 123,
                hogFunctionId: invocation.hogFunction.id,
                subscriptionId: params.mcp_event_subscription!.id,
            })
        )
        expect(JSON.stringify(jest.mocked(logger.warn).mock.calls)).not.toContain('private diagnostic')
        expect(JSON.stringify(jest.mocked(logger.warn).mock.calls)).not.toContain('private cause')
        expect(JSON.stringify(jest.mocked(logger.warn).mock.calls)).not.toContain('fake-user-credential')
    })

    it.each(['{}', 'not json'])('fails closed and diagnoses malformed authorization response %s', async (body) => {
        jest.mocked(internalFetch).mockResolvedValue({ status: 200, text: jest.fn().mockResolvedValue(body) } as any)
        expect(await prepareMcpEventDelivery({ invocation, params, internalApiBaseUrl: 'http://web:8000' })).toEqual({
            ok: false,
            status: 503,
        })
        expect(logger.warn).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ category: 'invalid_response' })
        )
    })
})
