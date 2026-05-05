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
        expect(response.capturedPostHogEvents[0].distinct_id).toMatch(/^http_log_[A-Za-z0-9+/]{22}$/)
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
        expect(response.capturedPostHogEvents[0].distinct_id).toMatch(/^http_log_[A-Za-z0-9+/]{22}$/)
    })

    it('snapshot: default config (forward_ip_and_user_agent on) emits PII fields', async () => {
        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(vercelLogDrain),
            }
        )

        expect(response.capturedPostHogEvents).toMatchSnapshot()
    })

    it('snapshot: forward_ip_and_user_agent disabled drops PII fields', async () => {
        const response = await tester.invoke(
            { forward_ip_and_user_agent: false },
            {
                request: createVercelRequest(vercelLogDrain),
            }
        )

        expect(response.capturedPostHogEvents).toMatchSnapshot()
    })

    it('should flatten all proxy properties (including PII) by default', async () => {
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

    it('should emit $ip, $raw_user_agent, and proxy_* PII by default and set $current_url from proxy data', async () => {
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
        expect(props.proxy_client_ip).toBe('120.75.16.101')
        expect(props.proxy_user_agent).toEqual(['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'])
        expect(props.$current_url).toBe('https://my-app.vercel.app/api/users?page=1')
    })

    it('should drop $ip, $raw_user_agent, and proxy_* PII when forward_ip_and_user_agent is disabled', async () => {
        const response = await tester.invoke(
            { forward_ip_and_user_agent: false },
            { request: createVercelRequest(vercelLogDrain) }
        )

        expect(response.error).toBeUndefined()
        const props = response.capturedPostHogEvents[0].properties
        expect(props.$ip).toBeUndefined()
        expect(props.$raw_user_agent).toBeUndefined()
        expect(props.proxy_client_ip).toBeUndefined()
        expect(props.proxy_user_agent).toBeUndefined()
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
        expect(response.capturedPostHogEvents[0].distinct_id).toMatch(/^http_log_[A-Za-z0-9+/]{22}$/)
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

    it('should extract $pathname and $host from URL', async () => {
        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(vercelLogDrain),
            }
        )

        expect(response.error).toBeUndefined()
        const props = response.capturedPostHogEvents[0].properties
        expect(props.$pathname).toBe('/api/users')
        expect(props.$host).toBe('my-app.vercel.app')
        expect(props.$referrer).toBe('https://my-app.vercel.app')
    })

    it('should extract UTM parameters from URL query string', async () => {
        const logWithUtm = {
            ...vercelLogDrain,
            proxy: {
                ...vercelLogDrain.proxy,
                path: '/api/users?utm_source=google&utm_medium=cpc&utm_campaign=summer_sale&utm_term=shoes&utm_content=banner_ad',
            },
        }

        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(logWithUtm),
            }
        )

        expect(response.error).toBeUndefined()
        const props = response.capturedPostHogEvents[0].properties
        expect(props.utm_source).toBe('google')
        expect(props.utm_medium).toBe('cpc')
        expect(props.utm_campaign).toBe('summer_sale')
        expect(props.utm_term).toBe('shoes')
        expect(props.utm_content).toBe('banner_ad')
    })

    it('should decode URL-encoded UTM values', async () => {
        const logWithEncodedUtm = {
            ...vercelLogDrain,
            proxy: {
                ...vercelLogDrain.proxy,
                path: '/api/users?utm_source=hello%20world&utm_campaign=summer%2B2024',
            },
        }

        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(logWithEncodedUtm),
            }
        )

        expect(response.error).toBeUndefined()
        const props = response.capturedPostHogEvents[0].properties
        expect(props.utm_source).toBe('hello world')
        expect(props.utm_campaign).toBe('summer+2024')
    })

    it('should set UTM properties to null when not present in URL', async () => {
        const logWithoutUtm = {
            ...vercelLogDrain,
            proxy: {
                ...vercelLogDrain.proxy,
                path: '/api/users?page=1&sort=name',
            },
        }

        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(logWithoutUtm),
            }
        )

        expect(response.error).toBeUndefined()
        const props = response.capturedPostHogEvents[0].properties
        expect(props.utm_source).toBeNull()
        expect(props.utm_medium).toBeNull()
        expect(props.utm_campaign).toBeNull()
        expect(props.utm_term).toBeNull()
        expect(props.utm_content).toBeNull()
    })

    it('should handle URLs without query strings', async () => {
        const logWithoutQuery = {
            ...vercelLogDrain,
            proxy: {
                ...vercelLogDrain.proxy,
                path: '/api/users',
            },
        }

        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(logWithoutQuery),
            }
        )

        expect(response.error).toBeUndefined()
        const props = response.capturedPostHogEvents[0].properties
        expect(props.$pathname).toBe('/api/users')
        expect(props.utm_source).toBeNull()
    })

    it('should treat empty UTM values as null', async () => {
        const logWithEmptyUtm = {
            ...vercelLogDrain,
            proxy: {
                ...vercelLogDrain.proxy,
                path: '/api/users?utm_source=&utm_medium=cpc',
            },
        }

        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(logWithEmptyUtm),
            }
        )

        expect(response.error).toBeUndefined()
        const props = response.capturedPostHogEvents[0].properties
        expect(props.utm_source).toBeNull()
        expect(props.utm_medium).toBe('cpc')
    })

    it('should handle malformed percent-encoding without crashing', async () => {
        const logWithMalformedEncoding = {
            ...vercelLogDrain,
            proxy: {
                ...vercelLogDrain.proxy,
                path: '/api/users?utm_campaign=100%free&utm_source=google',
            },
        }

        const response = await tester.invoke(
            {},
            {
                request: createVercelRequest(logWithMalformedEncoding),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(1)
        const props = response.capturedPostHogEvents[0].properties
        // Malformed value falls back to raw string
        expect(props.utm_campaign).toBe('100%free')
        // Valid encoding still works
        expect(props.utm_source).toBe('google')
    })

    describe('distinct_id_strategy', () => {
        const setMockedDay = (iso: string): void => {
            jest.spyOn(Date, 'now').mockReturnValue(DateTime.fromISO(iso, { zone: 'utc' }).toMillis())
        }

        const otherUaProxy = {
            ...vercelLogDrain.proxy,
            userAgent: ['curl/8.0'],
        }

        const otherIpProxy = {
            ...vercelLogDrain.proxy,
            clientIp: '203.0.113.7',
        }

        it('rotating_salt: same inputs same day → same id; different day → different id', async () => {
            setMockedDay('2025-01-01T00:00:00Z')
            const day1 = await tester.invoke(
                { salt_secret: 'test-salt', distinct_id_strategy: 'rotating_salt' },
                { request: createVercelRequest(vercelLogDrain) }
            )
            const day1Repeat = await tester.invoke(
                { salt_secret: 'test-salt', distinct_id_strategy: 'rotating_salt' },
                { request: createVercelRequest(vercelLogDrain) }
            )
            setMockedDay('2025-01-02T00:00:00Z')
            const day2 = await tester.invoke(
                { salt_secret: 'test-salt', distinct_id_strategy: 'rotating_salt' },
                { request: createVercelRequest(vercelLogDrain) }
            )

            const id1 = day1.capturedPostHogEvents[0].distinct_id
            const id1Repeat = day1Repeat.capturedPostHogEvents[0].distinct_id
            const id2 = day2.capturedPostHogEvents[0].distinct_id

            expect(id1).toMatch(/^http_log_[A-Za-z0-9+/]{22}$/)
            expect(id1Repeat).toBe(id1)
            expect(id2).not.toBe(id1)
            expect(day1.capturedPostHogEvents[0].properties.$distinct_id_strategy).toBe('rotating_salt')
        })

        it('rotating_salt: different UA on the same IP/day → different id', async () => {
            setMockedDay('2025-01-01T00:00:00Z')
            const baseline = await tester.invoke(
                { salt_secret: 'test-salt', distinct_id_strategy: 'rotating_salt' },
                { request: createVercelRequest(vercelLogDrain) }
            )
            const otherUa = await tester.invoke(
                { salt_secret: 'test-salt', distinct_id_strategy: 'rotating_salt' },
                { request: createVercelRequest({ ...vercelLogDrain, proxy: otherUaProxy }) }
            )

            expect(otherUa.capturedPostHogEvents[0].distinct_id).not.toBe(baseline.capturedPostHogEvents[0].distinct_id)
        })

        it('fixed_salt: same inputs different days → same id; rotating salt → different id', async () => {
            setMockedDay('2025-01-01T00:00:00Z')
            const day1 = await tester.invoke(
                { salt_secret: 'salt-v1', distinct_id_strategy: 'fixed_salt' },
                { request: createVercelRequest(vercelLogDrain) }
            )
            setMockedDay('2025-02-15T00:00:00Z')
            const day2 = await tester.invoke(
                { salt_secret: 'salt-v1', distinct_id_strategy: 'fixed_salt' },
                { request: createVercelRequest(vercelLogDrain) }
            )
            const rotated = await tester.invoke(
                { salt_secret: 'salt-v2', distinct_id_strategy: 'fixed_salt' },
                { request: createVercelRequest(vercelLogDrain) }
            )

            expect(day1.capturedPostHogEvents[0].distinct_id).toMatch(/^http_log_[A-Za-z0-9+/]{22}$/)
            expect(day2.capturedPostHogEvents[0].distinct_id).toBe(day1.capturedPostHogEvents[0].distinct_id)
            expect(rotated.capturedPostHogEvents[0].distinct_id).not.toBe(day1.capturedPostHogEvents[0].distinct_id)
            expect(day1.capturedPostHogEvents[0].properties.$distinct_id_strategy).toBe('fixed_salt')
        })

        it('ip: literal client IP after the prefix; stable across days', async () => {
            setMockedDay('2025-01-01T00:00:00Z')
            const day1 = await tester.invoke(
                { salt_secret: 'unused', distinct_id_strategy: 'ip' },
                { request: createVercelRequest(vercelLogDrain) }
            )
            setMockedDay('2025-03-01T00:00:00Z')
            const day2 = await tester.invoke(
                { salt_secret: 'unused', distinct_id_strategy: 'ip' },
                { request: createVercelRequest(vercelLogDrain) }
            )
            const otherIp = await tester.invoke(
                { salt_secret: 'unused', distinct_id_strategy: 'ip' },
                { request: createVercelRequest({ ...vercelLogDrain, proxy: otherIpProxy }) }
            )

            expect(day1.capturedPostHogEvents[0].distinct_id).toBe('http_log_120.75.16.101')
            expect(day2.capturedPostHogEvents[0].distinct_id).toBe('http_log_120.75.16.101')
            expect(otherIp.capturedPostHogEvents[0].distinct_id).toBe('http_log_203.0.113.7')
            expect(day1.capturedPostHogEvents[0].properties.$distinct_id_strategy).toBe('ip')
        })

        it('custom: substitutes placeholders into the template', async () => {
            const response = await tester.invoke(
                {
                    salt_secret: 'unused',
                    distinct_id_strategy: 'custom',
                    custom_template: 'tenant_{host}_{ip}',
                },
                { request: createVercelRequest(vercelLogDrain) }
            )

            expect(response.error).toBeUndefined()
            expect(response.capturedPostHogEvents[0].distinct_id).toBe(
                'http_log_tenant_my-app.vercel.app_120.75.16.101'
            )
            expect(response.capturedPostHogEvents[0].properties.$distinct_id_strategy).toBe('custom')
        })

        it('custom: substituted-to-empty template falls back to rotating_salt', async () => {
            const logWithoutUa = {
                ...vercelLogDrain,
                proxy: { ...vercelLogDrain.proxy, userAgent: [] },
            }
            const response = await tester.invoke(
                {
                    salt_secret: 'test-salt',
                    distinct_id_strategy: 'custom',
                    custom_template: '{ua}',
                },
                { request: createVercelRequest(logWithoutUa) }
            )

            expect(response.error).toBeUndefined()
            expect(response.capturedPostHogEvents[0].distinct_id).toMatch(/^http_log_[A-Za-z0-9+/]{22}$/)
            expect(response.capturedPostHogEvents[0].properties.$distinct_id_strategy).toBe('rotating_salt_fallback')
            expect(response.logs.map((l) => l.message)).toContainEqual(expect.stringContaining('substituted to empty'))
        })

        it('custom: {salt} placeholder is not interpreted (secret never reaches distinct_id)', async () => {
            const response = await tester.invoke(
                {
                    salt_secret: 'super-secret-salt',
                    distinct_id_strategy: 'custom',
                    custom_template: 'leak_{salt}_check',
                },
                { request: createVercelRequest(vercelLogDrain) }
            )

            expect(response.error).toBeUndefined()
            const distinctId = response.capturedPostHogEvents[0].distinct_id
            expect(distinctId).toBe('http_log_leak_{salt}_check')
            expect(distinctId).not.toContain('super-secret-salt')
        })

        it('custom: empty template falls back to rotating_salt and warns', async () => {
            const response = await tester.invoke(
                {
                    salt_secret: 'test-salt',
                    distinct_id_strategy: 'custom',
                    custom_template: '',
                },
                { request: createVercelRequest(vercelLogDrain) }
            )

            expect(response.error).toBeUndefined()
            expect(response.capturedPostHogEvents[0].distinct_id).toMatch(/^http_log_[A-Za-z0-9+/]{22}$/)
            expect(response.capturedPostHogEvents[0].properties.$distinct_id_strategy).toBe('rotating_salt_fallback')
            expect(response.logs.map((l) => l.message)).toContainEqual(
                expect.stringContaining('custom_template empty, falling back')
            )
        })

        it.each(['rotating_salt', 'fixed_salt', 'ip', 'custom'])(
            'strategy %s: omits $ip and $raw_user_agent when forward toggle is explicitly false',
            async (strategy) => {
                const response = await tester.invoke(
                    {
                        salt_secret: 'test-salt',
                        distinct_id_strategy: strategy,
                        custom_template: strategy === 'custom' ? 'k_{ip}' : undefined,
                        forward_ip_and_user_agent: false,
                    },
                    { request: createVercelRequest(vercelLogDrain) }
                )

                expect(response.error).toBeUndefined()
                const props = response.capturedPostHogEvents[0].properties
                expect(props.$ip).toBeUndefined()
                expect(props.$raw_user_agent).toBeUndefined()
            }
        )
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
