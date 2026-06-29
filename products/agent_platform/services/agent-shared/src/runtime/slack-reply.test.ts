import { describe, expect, it, vi } from 'vitest'

import { HttpFetcher } from './http-client'
import {
    decodeApprovalActionValue,
    postSlackApprovalButtons,
    postSlackReply,
    SlackStatusReporter,
    slackTextFromContent,
} from './slack-reply'

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

function httpReturning(res: Response | Error): { http: HttpFetcher; fetch: ReturnType<typeof vi.fn> } {
    const fetch = vi.fn(async () => {
        if (res instanceof Error) {
            throw res
        }
        return res
    })
    return { http: { fetch } as unknown as HttpFetcher, fetch }
}

describe('postSlackReply', () => {
    it('posts to chat.postMessage on the thread and returns true', async () => {
        const { http, fetch } = httpReturning(jsonResponse({ ok: true }))
        const ok = await postSlackReply(http, {
            token: 'xoxb-123',
            channel: 'C1',
            thread_ts: '111.222',
            text: 'here is your answer',
        })
        expect(ok).toBe(true)
        const [url, init] = fetch.mock.calls[0]
        expect(url).toBe('https://slack.com/api/chat.postMessage')
        expect((init as RequestInit).headers).toMatchObject({ Authorization: 'Bearer xoxb-123' })
        const body = JSON.parse((init as RequestInit).body as string)
        expect(body).toEqual({ channel: 'C1', thread_ts: '111.222', text: 'here is your answer' })
    })

    it('skips empty text without calling slack', async () => {
        const { http, fetch } = httpReturning(jsonResponse({ ok: true }))
        const ok = await postSlackReply(http, { token: 'xoxb', channel: 'C1', thread_ts: 't', text: '   ' })
        expect(ok).toBe(false)
        expect(fetch).not.toHaveBeenCalled()
    })

    it('warns and skips when the bot token is missing', async () => {
        const { http, fetch } = httpReturning(jsonResponse({ ok: true }))
        const warn = vi.fn()
        const ok = await postSlackReply(http, {
            token: undefined,
            channel: 'C1',
            thread_ts: 't',
            text: 'hi',
            logger: { warn },
        })
        expect(ok).toBe(false)
        expect(fetch).not.toHaveBeenCalled()
        expect(warn).toHaveBeenCalledWith(expect.objectContaining({ channel: 'C1' }), 'slack_reply_no_bot_token')
    })

    it('returns false and warns on a slack error body', async () => {
        const { http } = httpReturning(jsonResponse({ ok: false, error: 'channel_not_found' }))
        const warn = vi.fn()
        const ok = await postSlackReply(http, {
            token: 'xoxb',
            channel: 'C1',
            thread_ts: 't',
            text: 'hi',
            logger: { warn },
        })
        expect(ok).toBe(false)
        expect(warn).toHaveBeenCalledWith(
            expect.objectContaining({ slack_error: 'channel_not_found' }),
            'slack_reply_post_failed'
        )
    })

    it('swallows a thrown fetch and returns false', async () => {
        const { http } = httpReturning(new Error('network down'))
        const warn = vi.fn()
        const ok = await postSlackReply(http, {
            token: 'xoxb',
            channel: 'C1',
            thread_ts: 't',
            text: 'hi',
            logger: { warn },
        })
        expect(ok).toBe(false)
        expect(warn).toHaveBeenCalledWith(expect.objectContaining({ err: 'network down' }), 'slack_reply_post_threw')
    })
})

describe('postSlackApprovalButtons', () => {
    const opts = {
        token: 'xoxb-123',
        channel: 'C1',
        thread_ts: '111.222',
        sessionId: 'sess-1',
        requestId: 'req-1',
        toolName: '@posthog/team-delete',
    }

    it('posts Approve/Reject buttons whose values round-trip to the right callback routing', async () => {
        const { http, fetch } = httpReturning(jsonResponse({ ok: true }))
        const ok = await postSlackApprovalButtons(http, opts)
        expect(ok).toBe(true)

        const [url, init] = fetch.mock.calls[0]
        expect(url).toBe('https://slack.com/api/chat.postMessage')
        const body = JSON.parse((init as RequestInit).body as string)
        expect(body).toMatchObject({ channel: 'C1', thread_ts: '111.222' })

        // The buttons carry the opaque action values Slack echoes back on click;
        // the ingress decodes them to route the decision to the right approval.
        // This is the "right callback" assertion — a mis-encoded session/request
        // id here is exactly what breaks the decision round-trip.
        const actions = (body.blocks as Array<{ type: string; elements?: Array<{ value: string }> }>).find(
            (b) => b.type === 'actions'
        )
        const values = (actions?.elements ?? []).map((e) => decodeApprovalActionValue(e.value))
        expect(values).toEqual([
            { decision: 'approve', sessionId: 'sess-1', requestId: 'req-1' },
            { decision: 'reject', sessionId: 'sess-1', requestId: 'req-1' },
        ])
    })

    it('logs an info line with the routing data it sent (debug visibility)', async () => {
        const { http } = httpReturning(jsonResponse({ ok: true }))
        const info = vi.fn()
        await postSlackApprovalButtons(http, { ...opts, logger: { warn: vi.fn(), info } })
        expect(info).toHaveBeenCalledWith(
            expect.objectContaining({
                session_id: 'sess-1',
                request_id: 'req-1',
                channel: 'C1',
                thread_ts: '111.222',
                approve_value: expect.any(String),
                reject_value: expect.any(String),
            }),
            'slack_approval_buttons_post'
        )
    })

    it('warns and skips when the bot token is missing', async () => {
        const { http, fetch } = httpReturning(jsonResponse({ ok: true }))
        const warn = vi.fn()
        const ok = await postSlackApprovalButtons(http, { ...opts, token: undefined, logger: { warn } })
        expect(ok).toBe(false)
        expect(fetch).not.toHaveBeenCalled()
        expect(warn).toHaveBeenCalledWith(
            expect.objectContaining({ channel: 'C1' }),
            'slack_approval_buttons_no_bot_token'
        )
    })
})

describe('slackTextFromContent', () => {
    it('joins text blocks and ignores non-text / empty blocks', () => {
        const text = slackTextFromContent([
            { type: 'text', text: 'first' },
            { type: 'toolCall' },
            { type: 'text', text: 'second' },
            { type: 'text', text: '   ' },
        ])
        expect(text).toBe('first\n\nsecond')
    })

    it('drops whitespace-only blocks that sit between meaningful blocks', () => {
        const text = slackTextFromContent([
            { type: 'text', text: 'first' },
            { type: 'text', text: '   ' },
            { type: 'text', text: 'second' },
        ])
        expect(text).toBe('first\n\nsecond')
    })

    it('returns empty string for a pure tool-call turn', () => {
        expect(slackTextFromContent([{ type: 'toolCall' }])).toBe('')
    })
})

describe('SlackStatusReporter', () => {
    function recorder(): { http: HttpFetcher; calls: Array<{ url: string; body: Record<string, unknown> }> } {
        const calls: Array<{ url: string; body: Record<string, unknown> }> = []
        const http = {
            fetch: vi.fn(async (url: string | URL, init?: RequestInit) => {
                calls.push({
                    url: typeof url === 'string' ? url : url.toString(),
                    body: typeof init?.body === 'string' ? JSON.parse(init.body) : {},
                })
                return jsonResponse({ ok: true, ts: 'TS1' })
            }),
        } as unknown as HttpFetcher
        return { http, calls }
    }

    it('start posts once; a second start is a no-op', async () => {
        const { http, calls } = recorder()
        const r = new SlackStatusReporter({ http, token: 'xoxb', channel: 'C1', thread_ts: 't' })
        await r.start('working')
        await r.start('working again')
        const posts = calls.filter((c) => c.url.endsWith('chat.postMessage'))
        expect(posts).toHaveLength(1)
        expect(posts[0].body).toMatchObject({ channel: 'C1', thread_ts: 't', text: 'working' })
    })

    it('no-ops entirely without a token', async () => {
        const { http, calls } = recorder()
        const r = new SlackStatusReporter({ http, token: undefined, channel: 'C1', thread_ts: 't' })
        await r.start('working')
        await r.update('x')
        await r.clear()
        expect(calls).toHaveLength(0)
    })

    it('update edits the message and is throttled by minUpdateIntervalMs', async () => {
        const { http, calls } = recorder()
        let nowMs = 1000
        const r = new SlackStatusReporter({
            http,
            token: 'xoxb',
            channel: 'C1',
            thread_ts: 't',
            minUpdateIntervalMs: 1000,
            now: () => nowMs,
        })
        await r.start('working')
        await r.update('step 1') // within the throttle window → skipped
        expect(calls.filter((c) => c.url.endsWith('chat.update'))).toHaveLength(0)
        nowMs += 1000
        await r.update('step 2')
        const updates = calls.filter((c) => c.url.endsWith('chat.update'))
        expect(updates).toHaveLength(1)
        expect(updates[0].body).toMatchObject({ channel: 'C1', ts: 'TS1', text: 'step 2' })
    })

    it('clear deletes the message and is idempotent; start after clear re-posts', async () => {
        const { http, calls } = recorder()
        const r = new SlackStatusReporter({ http, token: 'xoxb', channel: 'C1', thread_ts: 't' })
        await r.start('working')
        await r.clear()
        await r.clear()
        const deletes = calls.filter((c) => c.url.endsWith('chat.delete'))
        expect(deletes).toHaveLength(1)
        expect(deletes[0].body).toMatchObject({ channel: 'C1', ts: 'TS1' })

        await r.start('working again')
        expect(calls.filter((c) => c.url.endsWith('chat.postMessage'))).toHaveLength(2)
    })
})
