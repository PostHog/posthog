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

    it('should capture a single log event', async () => {
        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(vercelLogDrain),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.capturedPostHogEvents).toHaveLength(1)
        expect(response.capturedPostHogEvents[0]).toMatchObject({
            event: '$log_http_hit',
            distinct_id: 'dpl_233NRGRjVZX1caZrXWtz5g1TAksD:643af4e3-975a-4cc7-9e7a-1eda11539d90',
        })
        expect(response.capturedPostHogEvents[0].properties.log_count).toBe(1)
        expect(response.capturedPostHogEvents[0].properties.first_log).toMatchObject({
            source: 'lambda',
            level: 'info',
            projectId: 'gdufoJxB6b9b1fEqr1jUtFkyavUU',
            statusCode: 200,
        })
    })

    it('should capture multiple logs from JSON array as batched event', async () => {
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
        expect(response.capturedPostHogEvents[0].properties.log_count).toBe(3)
        expect(response.capturedPostHogEvents[0].properties.logs).toHaveLength(3)
        expect(response.capturedPostHogEvents[0].properties.logs[0].id).toBe('log1')
        expect(response.capturedPostHogEvents[0].properties.logs[1].id).toBe('log2')
        expect(response.capturedPostHogEvents[0].properties.logs[2].id).toBe('log3')
    })

    it('should capture logs from NDJSON format as batched event', async () => {
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
        expect(response.capturedPostHogEvents[0].properties.log_count).toBe(2)
        expect(response.capturedPostHogEvents[0].properties.logs[0].id).toBe('ndjson1')
        expect(response.capturedPostHogEvents[0].properties.logs[1].id).toBe('ndjson2')
    })

    it('should filter by allowed sources', async () => {
        const logs = [
            { ...vercelLogDrain, id: 'log1', source: 'lambda' },
            { ...vercelLogDrain, id: 'log2', source: 'edge' },
            { ...vercelLogDrain, id: 'log3', source: 'build' },
        ]

        const response = await tester.invoke(
            {
                allowed_sources: ['lambda', 'edge'],
            },
            {
                request: createVercelRequest(logs),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(1)
        expect(response.capturedPostHogEvents[0].properties.log_count).toBe(2)
        expect(response.capturedPostHogEvents[0].properties.logs.map((l: any) => l.source)).toEqual(['lambda', 'edge'])
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
        expect(response.capturedPostHogEvents[0].properties.first_log.message).toHaveLength(100)
        expect(response.capturedPostHogEvents[0].properties.first_log.message_truncated).toBe(true)
    })

    it('should use log id as fallback for distinct_id when requestId is missing', async () => {
        const { requestId, ...logWithoutRequestId } = vercelLogDrain
        const log = { ...logWithoutRequestId }

        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(log),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents[0].distinct_id).toEqual(
            `${vercelLogDrain.deploymentId}:${vercelLogDrain.id}`
        )
    })

    it('should capture all Vercel log properties', async () => {
        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(vercelLogDrain),
            }
        )

        expect(response.capturedPostHogEvents).toMatchSnapshot()
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
