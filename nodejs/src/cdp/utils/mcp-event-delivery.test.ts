import type { CyclotronInvocationQueueParametersMcpEventType } from '~/cdp/schema/cyclotron'
import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'

import type { CyclotronJobInvocationHogFunction } from '../types'
import { prepareMcpEventDelivery } from './mcp-event-delivery'

jest.mock('~/common/utils/request', () => ({ internalFetch: jest.fn() }))

describe('MCP event delivery authorization', () => {
    const invocation = {
        id: '4f6c9f2a-5b1e-4f5b-9d3c-2a7e8c1d0b64',
        teamId: 123,
        hogFunction: {
            id: 'eae89749-3d0c-4ddb-875a-04771a7b9e34',
            inputs: {},
            encrypted_inputs: { mcp_credential: { value: 'fake-user-credential' } },
        },
    } as unknown as CyclotronJobInvocationHogFunction
    const params: CyclotronInvocationQueueParametersMcpEventType = {
        type: 'mcp_event',
        url: 'https://example.com/callback',
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
                    generation: params.mcp_event_subscription.generation,
                    filter_bytecode: params.mcp_event_subscription.filter_bytecode,
                    function_id: invocation.hogFunction.id,
                    url: params.url,
                    body: params.body,
                }),
            })
        )
        expect(JSON.stringify(params)).not.toContain('fake-user-credential')
    })

    it.each([
        [401, false],
        [403, false],
        [404, false],
        [400, false],
        [429, true],
        [500, true],
        [503, true],
    ])('classifies authorization status %s as retryable %s', async (status, expected) => {
        jest.mocked(internalFetch).mockResolvedValue({ status, dump: jest.fn().mockResolvedValue(undefined) } as any)
        expect(await prepareMcpEventDelivery({ invocation, params, internalApiBaseUrl: 'http://web:8000' })).toEqual({
            ok: false,
            retryable: expected,
        })
    })

    it.each(['seconds', 'date'])('preserves Retry-After as %s', async (format) => {
        const now = new Date('2026-01-01T00:00:00Z').getTime()
        jest.spyOn(Date, 'now').mockReturnValue(now)
        const retryAfter = format === 'seconds' ? '45' : new Date(now + 45_000).toUTCString()
        jest.mocked(internalFetch).mockResolvedValue({
            status: 429,
            headers: { 'retry-after': retryAfter },
            dump: jest.fn(),
        } as any)
        const result = await prepareMcpEventDelivery({ invocation, params, internalApiBaseUrl: 'http://web:8000' })
        expect(result).toMatchObject({ ok: false, retryable: true })
        if (!result.ok) {
            expect(result.retryAfterMs).toBe(45_000)
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
            retryable: true,
        })
        expect(logger.warn).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                category,
                teamId: 123,
                hogFunctionId: invocation.hogFunction.id,
                subscriptionId: params.mcp_event_subscription.id,
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
            retryable: true,
        })
        expect(logger.warn).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ category: 'invalid_response' })
        )
    })
})
