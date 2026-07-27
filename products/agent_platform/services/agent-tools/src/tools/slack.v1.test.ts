import { vi } from 'vitest'

import type { HttpFetcher, ToolContext } from '@posthog/agent-shared'

import { makeCtx } from '../test-helpers'
import {
    slackPostMessageV1,
    slackReactV1,
    slackReadChannelV1,
    slackReadThreadV1,
    slackUpdateMessageV1,
} from './slack.v1'

describe('slack.* tools', () => {
    /**
     * Build an HttpFetcher that returns a canned `{ ok: true, ...body }` Slack
     * envelope on every call.
     */
    function mockHttp(body: Record<string, unknown>): HttpFetcher {
        return {
            fetch: vi.fn(
                async () =>
                    ({
                        ok: true,
                        status: 200,
                        json: async () => ({ ok: true, ...body }),
                    }) as unknown as Response
            ),
        }
    }

    function ctxWithSlack(http: HttpFetcher, token: string = 'xoxb-test'): ToolContext {
        return makeCtx({
            http,
            secret: (name) => (name === 'SLACK_BOT_TOKEN' ? token : undefined),
        })
    }

    it('post_message returns ts + channel', async () => {
        const http = mockHttp({ ts: '123.456', channel: 'C01' })
        const out = await slackPostMessageV1.run({ channel: 'C01', text: 'hi' }, ctxWithSlack(http))
        expect(out).toEqual({ ts: '123.456', channel: 'C01' })
    })

    it('post_message attaches the agent bot token as bearer auth', async () => {
        const fetchSpy = vi.fn(
            async () =>
                ({
                    ok: true,
                    status: 200,
                    json: async () => ({ ok: true, ts: '1', channel: 'C01' }),
                }) as unknown as Response
        )
        const http: HttpFetcher = { fetch: fetchSpy }
        await slackPostMessageV1.run({ channel: 'C01', text: 'hi' }, ctxWithSlack(http, 'xoxb-specific'))
        const calls = fetchSpy.mock.calls as unknown as Array<[string, RequestInit]>
        expect((calls[0][1].headers as Record<string, string>).Authorization).toBe('Bearer xoxb-specific')
    })

    it('rejects when SLACK_BOT_TOKEN is not set', async () => {
        await expect(slackPostMessageV1.run({ channel: 'C01', text: 'hi' }, makeCtx())).rejects.toThrow(
            /SLACK_BOT_TOKEN/
        )
    })

    it('update_message returns ok', async () => {
        const http = mockHttp({})
        const out = await slackUpdateMessageV1.run({ channel: 'C01', ts: '123.456', text: 'edit' }, ctxWithSlack(http))
        expect(out).toEqual({ ok: true })
    })

    it('react returns ok', async () => {
        const http = mockHttp({})
        const out = await slackReactV1.run({ channel: 'C01', ts: '123.456', name: 'fire' }, ctxWithSlack(http))
        expect(out).toEqual({ ok: true })
    })

    it('read_channel returns projected messages + pagination', async () => {
        const fetchSpy = vi.fn(
            async () =>
                ({
                    ok: true,
                    status: 200,
                    json: async () => ({
                        ok: true,
                        messages: [
                            {
                                ts: '111.222',
                                user: 'U01',
                                text: 'hello',
                                thread_ts: '111.222',
                                reply_count: 3,
                                extra_field_we_drop: true,
                            },
                            {
                                ts: '111.221',
                                bot_id: 'B01',
                                username: 'alertbot',
                                text: 'PAGE',
                                subtype: 'bot_message',
                            },
                        ],
                        has_more: true,
                        response_metadata: { next_cursor: 'cur-abc' },
                    }),
                }) as unknown as Response
        )
        const http: HttpFetcher = { fetch: fetchSpy }
        const out = await slackReadChannelV1.run({ channel: 'C01', limit: 50, oldest: '100.0' }, ctxWithSlack(http))
        expect(out.messages).toEqual([
            {
                ts: '111.222',
                user: 'U01',
                bot_id: undefined,
                username: undefined,
                text: 'hello',
                subtype: undefined,
                thread_ts: '111.222',
                reply_count: 3,
            },
            {
                ts: '111.221',
                user: undefined,
                bot_id: 'B01',
                username: 'alertbot',
                text: 'PAGE',
                subtype: 'bot_message',
                thread_ts: undefined,
                reply_count: undefined,
            },
        ])
        expect(out.has_more).toBe(true)
        expect(out.next_cursor).toBe('cur-abc')
        const calls = fetchSpy.mock.calls as unknown as Array<[string, RequestInit]>
        const body = Object.fromEntries(new URLSearchParams(calls[0][1].body as string))
        expect(body).toMatchObject({ channel: 'C01', limit: '50', oldest: '100.0' })
        expect(body).not.toHaveProperty('latest')
        expect(body).not.toHaveProperty('cursor')
    })

    it('read_channel clamps limit to [1, 200]', async () => {
        const fetchSpy = vi.fn(
            async () =>
                ({
                    ok: true,
                    status: 200,
                    json: async () => ({ ok: true, messages: [], has_more: false }),
                }) as unknown as Response
        )
        const http: HttpFetcher = { fetch: fetchSpy }
        await slackReadChannelV1.run({ channel: 'C01', limit: 9999 }, ctxWithSlack(http))
        const calls = fetchSpy.mock.calls as unknown as Array<[string, RequestInit]>
        const bodyHigh = Object.fromEntries(new URLSearchParams(calls[0][1].body as string))
        expect(bodyHigh.limit).toBe('200')

        await slackReadChannelV1.run({ channel: 'C01', limit: 0 }, ctxWithSlack(http))
        const bodyLow = Object.fromEntries(new URLSearchParams(calls[1][1].body as string))
        expect(bodyLow.limit).toBe('1')
    })

    it('read_channel omits next_cursor when slack returns empty string', async () => {
        const http = mockHttp({ messages: [], has_more: false, response_metadata: { next_cursor: '' } })
        const out = await slackReadChannelV1.run({ channel: 'C01' }, ctxWithSlack(http))
        expect(out.next_cursor).toBeUndefined()
        expect(out.has_more).toBe(false)
    })

    it('read_thread passes ts as the parent and projects messages', async () => {
        const fetchSpy = vi.fn(
            async () =>
                ({
                    ok: true,
                    status: 200,
                    json: async () => ({
                        ok: true,
                        messages: [
                            { ts: '111.222', user: 'U01', text: 'parent', thread_ts: '111.222', reply_count: 1 },
                            { ts: '111.333', user: 'U02', text: 'reply', thread_ts: '111.222' },
                        ],
                        has_more: false,
                    }),
                }) as unknown as Response
        )
        const http: HttpFetcher = { fetch: fetchSpy }
        const out = await slackReadThreadV1.run({ channel: 'C01', thread_ts: '111.222' }, ctxWithSlack(http))
        expect(out.messages.map((m) => m.text)).toEqual(['parent', 'reply'])
        expect(out.has_more).toBe(false)
        const calls = fetchSpy.mock.calls as unknown as Array<[string, RequestInit]>
        const body = Object.fromEntries(new URLSearchParams(calls[0][1].body as string))
        expect(body).toMatchObject({ channel: 'C01', ts: '111.222', limit: '50' })
    })

    it('sends form-encoded params — Slack read methods reject JSON', async () => {
        const fetchSpy = vi.fn(
            async () =>
                ({
                    ok: true,
                    status: 200,
                    json: async () => ({ ok: true, messages: [], has_more: false }),
                }) as unknown as Response
        )
        const http: HttpFetcher = { fetch: fetchSpy }
        await slackReadThreadV1.run({ channel: 'C01', thread_ts: '9.9' }, ctxWithSlack(http))
        const calls = fetchSpy.mock.calls as unknown as Array<[string, RequestInit]>
        expect((calls[0][1].headers as Record<string, string>)['Content-Type']).toBe(
            'application/x-www-form-urlencoded'
        )
        expect(calls[0][1].body).toBe('channel=C01&ts=9.9&limit=50')
    })

    it('propagates slack api errors', async () => {
        const http: HttpFetcher = {
            fetch: vi.fn(
                async () =>
                    ({
                        ok: true,
                        status: 200,
                        json: async () => ({ ok: false, error: 'channel_not_found' }),
                    }) as unknown as Response
            ),
        }
        await expect(slackPostMessageV1.run({ channel: 'C99', text: 'hi' }, ctxWithSlack(http))).rejects.toThrow(
            /channel_not_found/
        )
    })

    it('surfaces slack warning + field detail so the agent can self-correct', async () => {
        const http: HttpFetcher = {
            fetch: vi.fn(
                async () =>
                    ({
                        ok: true,
                        status: 200,
                        json: async () => ({
                            ok: false,
                            error: 'invalid_arguments',
                            warning: 'missing_charset',
                            response_metadata: { messages: ['[ERROR] missing required field: ts'] },
                        }),
                    }) as unknown as Response
            ),
        }
        await expect(slackPostMessageV1.run({ channel: 'C01', text: 'hi' }, ctxWithSlack(http))).rejects.toThrow(
            /missing_charset.*missing required field: ts/
        )
    })
})
