import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import vercelLogDrain from './__tests__/vercel-log-drain.json'
import { template } from './vercel_log_drain.template'

describe('vercel log drain template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should capture a single log event with flattened properties', async () => {
        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(vercelLogDrain),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.capturedPostHogEvents).toHaveLength(1)
        expect(response.capturedPostHogEvents[0].event).toEqual('$http_log')
        expect(response.capturedPostHogEvents[0].distinct_id).toMatch(/^vercel_[a-f0-9]{64}$/)
        expect(response.capturedPostHogEvents[0].properties).toMatchObject({
            source: 'lambda',
            level: 'info',
            project_id: 'gdufoJxB6b9b1fEqr1jUtFkyavUU',
            status_code: 200,
        })
    })

    it('should capture only first log from JSON array and log warning', async () => {
        const logs = [
            { ...vercelLogDrain, id: 'log1', requestId: 'req1' },
            { ...vercelLogDrain, id: 'log2', requestId: 'req2', source: 'edge' },
            { ...vercelLogDrain, id: 'log3', requestId: 'req3', source: 'build' },
        ]

        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(logs),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(1)
        // Only first log is captured
        expect(response.capturedPostHogEvents[0].properties.vercel_log_id).toBe('log1')
        expect(response.capturedPostHogEvents[0].properties.source).toBe('lambda')
        // Warning should be logged about dropped logs
        expect(response.logs.map((l) => l.message)).toContainEqual(
            expect.stringContaining('Dropped 2 additional log(s)')
        )
    })

    it('should capture only first log from NDJSON format', async () => {
        const log1 = { ...vercelLogDrain, id: 'ndjson1', requestId: 'ndjson-req1' }
        const log2 = { ...vercelLogDrain, id: 'ndjson2', requestId: 'ndjson-req2' }
        const ndjsonBody = `${JSON.stringify(log1)}\n${JSON.stringify(log2)}`

        const response = await tester.invoke(
            {},
            {
                request: {
                    method: 'POST',
                    headers: {},
                    body: {},
                    stringBody: ndjsonBody,
                    query: {},
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(1)
        expect(response.capturedPostHogEvents[0].properties.vercel_log_id).toBe('ndjson1')
    })

    it('should return 405 for non-POST methods', async () => {
        const response = await tester.invoke(
            {},
            {
                request: {
                    method: 'GET',
                    headers: {},
                    body: {},
                    stringBody: '',
                    query: {},
                },
            }
        )

        expect(response.execResult).toMatchObject({
            httpResponse: {
                status: 405,
                body: 'Method not allowed',
            },
        })
    })

    it('should return 401 for invalid authorization header', async () => {
        const response = await tester.invoke(
            {
                auth_header: 'Bearer secret123',
            },
            {
                request: {
                    ...createVercelRequest(vercelLogDrain),
                    headers: {
                        authorization: 'Bearer wrong',
                    },
                },
            }
        )

        expect(response.execResult).toMatchObject({
            httpResponse: {
                status: 401,
                body: 'Unauthorized',
            },
        })
    })

    it('should allow valid authorization header', async () => {
        const response = await tester.invoke(
            {
                auth_header: 'Bearer secret123',
            },
            {
                request: {
                    ...createVercelRequest(vercelLogDrain),
                    headers: {
                        authorization: 'Bearer secret123',
                    },
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(1)
    })

    it('should return 400 for empty body', async () => {
        const response = await tester.invoke(
            {},
            {
                request: {
                    method: 'POST',
                    headers: {},
                    body: {},
                    stringBody: '',
                    query: {},
                },
            }
        )

        expect(response.execResult).toMatchObject({
            httpResponse: {
                status: 400,
                body: {
                    error: 'No valid Vercel log objects found',
                },
            },
        })
    })

    it('should return 400 for invalid log objects', async () => {
        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest({ foo: 'bar' }),
            }
        )

        expect(response.execResult).toMatchObject({
            httpResponse: {
                status: 400,
                body: {
                    error: 'No valid Vercel log objects found',
                },
            },
        })
    })

    it('should truncate long messages', async () => {
        const longMessage = 'a'.repeat(1000)
        const log = { ...vercelLogDrain, message: longMessage }

        const response = await tester.invoke(
            {
                max_message_len: 100,
            },
            {
                request: createVercelRequest(log),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents[0].properties.message).toHaveLength(100)
        expect(response.capturedPostHogEvents[0].properties.message_truncated).toBe(true)
    })

    it('should use consistent distinct_id when requestId is missing', async () => {
        const { requestId, ...logWithoutRequestId } = vercelLogDrain
        const log = { ...logWithoutRequestId }

        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(log),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents[0].distinct_id).toMatch(/^vercel_[a-f0-9]{64}$/)
    })

    it('should capture all Vercel log properties with snake_case naming', async () => {
        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(vercelLogDrain),
            }
        )

        expect(response.capturedPostHogEvents).toMatchSnapshot()
    })

    it('should flatten proxy properties', async () => {
        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(vercelLogDrain),
            }
        )

        expect(response.error).toBeUndefined()
        const props = response.capturedPostHogEvents[0].properties
        expect(props.proxy_method).toBe('GET')
        expect(props.proxy_host).toBe('my-app.vercel.app')
        expect(props.proxy_path).toBe('/api/users?page=1')
        expect(props.proxy_client_ip).toBe('120.75.16.101')
        expect(props.proxy_vercel_cache).toBe('MISS')
    })

    it('should set PostHog standard properties from proxy data', async () => {
        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(vercelLogDrain),
            }
        )

        expect(response.error).toBeUndefined()
        const props = response.capturedPostHogEvents[0].properties
        expect(props.$ip).toBe('120.75.16.101')
        expect(props.$raw_user_agent).toBe('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
        expect(props.$current_url).toBe('https://my-app.vercel.app/api/users?page=1')
    })

    it('should handle logs with null message without crashing', async () => {
        const { message, ...logWithoutMessage } = vercelLogDrain
        const log = { ...logWithoutMessage, message: null }

        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(log),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(1)
        expect(response.capturedPostHogEvents[0].properties.message).toBeNull()
        expect(response.capturedPostHogEvents[0].properties.message_truncated).toBe(false)
    })

    it('should handle logs without proxy field', async () => {
        const { proxy, ...logWithoutProxy } = vercelLogDrain
        const log = { ...logWithoutProxy }

        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(log),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(1)
        expect(response.capturedPostHogEvents[0].distinct_id).toMatch(/^vercel_[a-f0-9]{64}$/)
        // Proxy fields should be null when proxy is missing
        expect(response.capturedPostHogEvents[0].properties.proxy_method).toBeNull()
    })

    it('should fall back to request.body when stringBody is empty', async () => {
        const response = await tester.invoke(
            {},
            {
                request: {
                    method: 'POST',
                    headers: {},
                    body: vercelLogDrain,
                    stringBody: '',
                    query: {},
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(1)
        expect(response.capturedPostHogEvents[0].properties).toMatchObject({
            source: 'lambda',
            level: 'info',
            project_id: 'gdufoJxB6b9b1fEqr1jUtFkyavUU',
        })
    })

    it('should fall back to request.body array when stringBody is empty', async () => {
        const logs = [
            { ...vercelLogDrain, id: 'body1' },
            { ...vercelLogDrain, id: 'body2' },
        ]

        const response = await tester.invoke(
            {},
            {
                request: {
                    method: 'POST',
                    headers: {},
                    body: logs,
                    stringBody: '',
                    query: {},
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(1)
        expect(response.capturedPostHogEvents[0].properties.vercel_log_id).toBe('body1')
    })
})

const createVercelRequest = (body: Record<string, any> | Record<string, any>[]) => {
    const payload = JSON.stringify(body)
    return {
        method: 'POST',
        body: body,
        stringBody: payload,
        headers: {},
        query: {},
    }
}
