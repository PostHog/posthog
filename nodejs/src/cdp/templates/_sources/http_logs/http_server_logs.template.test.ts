import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template as cloudflareLogsTemplate } from '../cloudflare/cloudflare_logs.template'
import { template as httpServerLogsTemplate } from './http_server_logs.template'

const createRequest = (body: Record<string, any>, headers: Record<string, string> = {}) => ({
    method: 'POST',
    headers,
    body,
    stringBody: JSON.stringify(body),
    query: {},
})

describe('http log source templates', () => {
    const tester = new TemplateTester(httpServerLogsTemplate)
    const cloudflareTester = new TemplateTester(cloudflareLogsTemplate)

    beforeEach(async () => {
        await tester.beforeEach()
        await cloudflareTester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('captures one $http_log event from a full url, parsing host, pathname, and UTM params', async () => {
        const response = await tester.invoke(
            {},
            {
                request: createRequest({
                    url: 'https://example.com/pricing?utm_source=newsletter&utm_campaign=launch',
                    method: 'GET',
                    status_code: 200,
                    ip: '203.0.113.7',
                    user_agent: 'Mozilla/5.0',
                    referrer: 'https://www.google.com/',
                    timestamp: 1735689600000,
                }),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.capturedPostHogEvents).toHaveLength(1)
        expect(response.capturedPostHogEvents[0].event).toEqual('$http_log')
        expect(response.capturedPostHogEvents[0].distinct_id).toMatch(/^http_log_[A-Za-z0-9+/]{22}$/)
        expect(response.capturedPostHogEvents[0].properties).toMatchObject({
            $current_url: 'https://example.com/pricing?utm_source=newsletter&utm_campaign=launch',
            $host: 'example.com',
            $pathname: '/pricing',
            $referrer: 'https://www.google.com/',
            $ip: '203.0.113.7',
            $raw_user_agent: 'Mozilla/5.0',
            $process_person_profile: false,
            utm_source: 'newsletter',
            utm_campaign: 'launch',
            method: 'GET',
            status_code: 200,
            log_timestamp_ms: 1735689600000,
        })
    })

    it('builds the url from separate host, path, and scheme fields when url is absent', async () => {
        const response = await tester.invoke(
            {},
            {
                request: createRequest({
                    host: 'example.com',
                    path: '/docs/start?ref=nav',
                    scheme: 'http',
                    user_agent: 'GPTBot/1.0',
                }),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(1)
        expect(response.capturedPostHogEvents[0].properties).toMatchObject({
            $current_url: 'http://example.com/docs/start?ref=nav',
            $host: 'example.com',
            $pathname: '/docs/start',
        })
    })

    it.each([
        ['array of records', [{ url: 'https://example.com/a' }, { url: 'https://example.com/b' }]],
        ['record without url or host', { method: 'GET', status_code: 200 }],
    ])('rejects a %s with 400 and captures nothing', async (_name, body) => {
        const response = await tester.invoke(
            {},
            {
                request: createRequest(body as any),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(0)
        expect(response.execResult).toMatchObject({ httpResponse: { status: 400 } })
    })

    it('returns 401 and captures nothing when the auth header does not match', async () => {
        const response = await tester.invoke(
            { auth_header: 'Bearer secret123' },
            {
                request: createRequest({ url: 'https://example.com/' }, { authorization: 'Bearer wrong' }),
            }
        )

        expect(response.capturedPostHogEvents).toHaveLength(0)
        expect(response.execResult).toMatchObject({ httpResponse: { status: 401 } })
    })

    it.each([
        ['/static/app.js', 0],
        ['/pricing', 1],
        ['/docs/index.html', 1],
    ])('page_routes_only: %s captures %i event(s) and always acks with 200', async (path, captured) => {
        const response = await tester.invoke(
            { page_routes_only: true },
            {
                request: createRequest({ url: `https://example.com${path}` }),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(captured)
        expect(response.execResult).toMatchObject({ httpResponse: { status: 200 } })
    })

    it('passes extra properties through without letting them override standard fields', async () => {
        const response = await tester.invoke(
            {},
            {
                request: createRequest({
                    url: 'https://example.com/a',
                    properties: {
                        region: 'iad1',
                        $current_url: 'https://spoofed.example.net/',
                    },
                }),
            }
        )

        expect(response.capturedPostHogEvents[0].properties).toMatchObject({
            region: 'iad1',
            $current_url: 'https://example.com/a',
        })
    })

    it('uses the raw IP as distinct id with the ip strategy and strips identifiers when forwarding is off', async () => {
        const response = await tester.invoke(
            { distinct_id_strategy: 'ip', forward_ip_and_user_agent: false },
            {
                request: createRequest({
                    url: 'https://example.com/a',
                    ip: '203.0.113.7',
                    user_agent: 'Mozilla/5.0',
                }),
            }
        )

        expect(response.capturedPostHogEvents[0].distinct_id).toEqual('http_log_203.0.113.7')
        expect(response.capturedPostHogEvents[0].properties.$ip).toBeUndefined()
        expect(response.capturedPostHogEvents[0].properties.$raw_user_agent).toBeUndefined()
    })

    it('cloudflare template captures a worker-shaped payload with cloudflare properties', async () => {
        const response = await cloudflareTester.invoke(
            {},
            {
                request: createRequest({
                    url: 'https://example.com/pricing',
                    method: 'GET',
                    status_code: 200,
                    ip: '203.0.113.7',
                    user_agent: 'ClaudeBot/1.0',
                    properties: {
                        cloudflare_country: 'US',
                        cloudflare_bot_score: 1,
                    },
                }),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(1)
        expect(response.capturedPostHogEvents[0].event).toEqual('$http_log')
        expect(response.capturedPostHogEvents[0].properties).toMatchObject({
            $pathname: '/pricing',
            $raw_user_agent: 'ClaudeBot/1.0',
            cloudflare_country: 'US',
            cloudflare_bot_score: 1,
        })
    })
})
