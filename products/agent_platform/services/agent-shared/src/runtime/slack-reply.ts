/**
 * Slack reply relay: posts an agent's finalized assistant message into its
 * originating Slack thread. The platform owns Slack delivery for slack-triggered
 * sessions — the model just replies in natural language and the runner relays
 * each completed message here, mirroring how the chat trigger streams text back
 * to the console. `@posthog/slack-post-message` stays available for advanced
 * sends (Block Kit, other channels, DMs, edits).
 *
 * Never throws — a Slack hiccup must not break the agent loop. Failures log at
 * warn and return false.
 */

import { HttpFetcher } from './http-client'
import { markdownToMrkdwn } from './slack-mrkdwn'

/** Join the text blocks of an assistant message into one Slack message body. */
export function slackTextFromContent(content: ReadonlyArray<{ type: string; text?: string }>): string {
    return content
        .filter(
            (b): b is { type: string; text: string } =>
                b.type === 'text' && typeof b.text === 'string' && b.text.trim().length > 0
        )
        .map((b) => b.text.trim())
        .join('\n\n')
}

/** Native status is plain text ("<App> <status>") — strip emoji shortcodes and
 *  markdown emphasis that only render in a normal message. */
export function toPlainStatus(text: string): string {
    return text
        .replace(/:[a-z0-9_+-]+:/gi, '')
        .replace(/[*_`]/g, '')
        .replace(/\s+/g, ' ')
        .trim()
}

export interface SlackReplyLogger {
    warn: (meta: Record<string, unknown>, msg: string) => void
    info?: (meta: Record<string, unknown>, msg: string) => void
}

export interface PostSlackReplyOpts {
    token: string | undefined
    channel: string
    thread_ts: string
    text: string
    sessionId?: string
    logger?: SlackReplyLogger
}

export interface SlackStatusReporterDeps {
    http: HttpFetcher
    token: string | undefined
    channel: string
    thread_ts: string
    sessionId?: string
    logger?: SlackReplyLogger
    /** Min gap between status updates — Slack rate-limits both chat.update and
     *  assistant.threads.setStatus. Default 1000ms. */
    minUpdateIntervalMs?: number
    /** Injectable clock for tests. Default Date.now. */
    now?: () => number
    /**
     * How to render the "working on it" indicator (default `'native'`):
     *   - `'native'` — Slack's native `assistant.threads.setStatus`, which shows
     *     "<App> <status>" in the agent surface and auto-clears when the app
     *     posts its reply. `clear()` is a no-op. This is the standard rendering:
     *     every Slack agent is a native agent surface.
     *   - `'simulated'` — a normal thread message we post / chat.update /
     *     chat.delete. `setStatus` only renders inside an assistant/DM thread, so
     *     this is the right rendering for a plain channel @-mention thread; the
     *     driver does not select it yet (a follow-up can, once the session's
     *     DM-ness is threaded through to the runner).
     */
    mode?: 'native' | 'simulated'
}

/**
 * The "working on it" status shown while a turn is in flight, cleared when the
 * agent's real reply lands. Two renderings selected by `deps.mode` (default
 * `native`):
 *
 *   - `native`: Slack's `assistant.threads.setStatus` — the real agent thinking
 *     indicator. It auto-clears when the app posts a message, so `clear()` does
 *     nothing; the reply relay in the driver clears it implicitly.
 *   - `simulated`: a normal thread message we post / `chat.update` / `chat.delete`
 *     (not a true Slack ephemeral — those need a response_url and can't be
 *     edited). For plain channel threads, where the native indicator has no
 *     assistant surface to render in.
 *
 * Never throws — a Slack hiccup must not break the agent loop.
 */
export class SlackStatusReporter {
    private ts: string | null = null
    private lastText: string | null = null
    private lastUpdateMs = 0

    constructor(private readonly deps: SlackStatusReporterDeps) {}

    private get mode(): 'native' | 'simulated' {
        return this.deps.mode ?? 'native'
    }

    /** Post/show the status if it isn't already shown. */
    async start(text: string): Promise<void> {
        if (!this.deps.token) {
            return
        }
        if (this.mode === 'native') {
            this.lastText = text
            this.lastUpdateMs = this.clock()
            await this.setNativeStatus(text)
            return
        }
        if (this.ts) {
            return
        }
        const res = await this.call('chat.postMessage', {
            channel: this.deps.channel,
            thread_ts: this.deps.thread_ts,
            text,
        })
        if (res?.ts) {
            this.ts = res.ts
            this.lastText = text
            this.lastUpdateMs = this.clock()
        }
    }

    /** Update the status text. Throttled + best-effort. */
    async update(text: string): Promise<void> {
        if (!this.deps.token || text === this.lastText) {
            return
        }
        const now = this.clock()
        if (now - this.lastUpdateMs < (this.deps.minUpdateIntervalMs ?? 1000)) {
            return
        }
        if (this.mode === 'native') {
            this.lastText = text
            this.lastUpdateMs = now
            await this.setNativeStatus(text)
            return
        }
        if (!this.ts) {
            return
        }
        this.lastText = text
        this.lastUpdateMs = now
        await this.call('chat.update', { channel: this.deps.channel, ts: this.ts, text })
    }

    /** Remove the status. Native status auto-clears on reply, so it's a no-op
     *  there; simulated deletes the message. Idempotent. */
    async clear(): Promise<void> {
        if (!this.deps.token || this.mode === 'native') {
            return
        }
        if (!this.ts) {
            return
        }
        const ts = this.ts
        this.ts = null
        await this.call('chat.delete', { channel: this.deps.channel, ts })
    }

    /** Native indicator via assistant.threads.setStatus (plain text only). */
    private async setNativeStatus(text: string): Promise<void> {
        await this.call('assistant.threads.setStatus', {
            channel_id: this.deps.channel,
            thread_ts: this.deps.thread_ts,
            status: toPlainStatus(text),
        })
    }

    private clock(): number {
        return (this.deps.now ?? Date.now)()
    }

    private async call(method: string, body: Record<string, unknown>): Promise<{ ok?: boolean; ts?: string } | null> {
        try {
            const res = await this.deps.http.fetch(`https://slack.com/api/${method}`, {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${this.deps.token}`,
                    'Content-Type': 'application/json; charset=utf-8',
                },
                body: JSON.stringify(body),
            })
            let parsed: { ok?: boolean; ts?: string; error?: string } = {}
            try {
                parsed = (await res.json()) as { ok?: boolean; ts?: string; error?: string }
            } catch {
                // Non-JSON — treated as a failure via res.ok below.
            }
            if (!res.ok || parsed.ok === false) {
                this.deps.logger?.warn(
                    {
                        session_id: this.deps.sessionId,
                        channel: this.deps.channel,
                        method,
                        status: res.status,
                        slack_error: parsed.error ?? null,
                    },
                    'slack_status_failed'
                )
                return null
            }
            return parsed
        } catch (err) {
            this.deps.logger?.warn(
                {
                    session_id: this.deps.sessionId,
                    channel: this.deps.channel,
                    method,
                    err: err instanceof Error ? err.message : String(err),
                },
                'slack_status_threw'
            )
            return null
        }
    }
}

/**
 * Codec for the opaque Slack button `value` carrying a tool-approval decision.
 * Shared by the poster (the runner, which renders the buttons when a
 * `principal` approval queues) and the receiver (the ingress interactivity
 * handler). `approval:<approve|reject>:<sessionId>:<requestId>`.
 */
export function encodeApprovalActionValue(opts: {
    sessionId: string
    requestId: string
    decision: 'approve' | 'reject'
}): string {
    return `approval:${opts.decision}:${opts.sessionId}:${opts.requestId}`
}

export function decodeApprovalActionValue(
    value: string | undefined
): { sessionId: string; requestId: string; decision: 'approve' | 'reject' } | null {
    if (!value) {
        return null
    }
    const parts = value.split(':')
    if (parts.length !== 4 || parts[0] !== 'approval') {
        return null
    }
    const decision = parts[1]
    if (decision !== 'approve' && decision !== 'reject') {
        return null
    }
    return { decision, sessionId: parts[2], requestId: parts[3] }
}

export interface PostApprovalButtonsOpts {
    token: string | undefined
    channel: string
    thread_ts: string
    sessionId: string
    requestId: string
    /** Tool the model proposed — shown in the prompt so the approver has context. */
    toolName: string
    logger?: SlackReplyLogger
}

/**
 * Post an in-thread Block Kit message with Approve / Reject buttons for a queued
 * `principal` approval, so the session owner can decide right in Slack. The
 * buttons' opaque value round-trips through `decodeApprovalActionValue` at the
 * ingress interactivity handler, which enforces principal-match before deciding.
 * Best-effort: never throws (a Slack hiccup must not break the agent loop).
 */
export async function postSlackApprovalButtons(http: HttpFetcher, opts: PostApprovalButtonsOpts): Promise<boolean> {
    if (!opts.token) {
        opts.logger?.warn({ session_id: opts.sessionId, channel: opts.channel }, 'slack_approval_buttons_no_bot_token')
        return false
    }
    const value = (decision: 'approve' | 'reject'): string =>
        encodeApprovalActionValue({ sessionId: opts.sessionId, requestId: opts.requestId, decision })
    const blocks = [
        {
            type: 'section',
            text: { type: 'mrkdwn', text: `*Approval needed* — \`${opts.toolName}\` is waiting for your go-ahead.` },
        },
        {
            type: 'actions',
            elements: [
                {
                    type: 'button',
                    text: { type: 'plain_text', text: 'Approve' },
                    style: 'primary',
                    action_id: 'approval_approve',
                    value: value('approve'),
                },
                {
                    type: 'button',
                    text: { type: 'plain_text', text: 'Reject' },
                    style: 'danger',
                    action_id: 'approval_reject',
                    value: value('reject'),
                },
            ],
        },
    ]
    // Visibility for debugging the approval round-trip: log exactly what routing
    // data we put in the buttons. Slack echoes these opaque `value`s back on
    // click and the ingress interactivity handler decodes them to find the
    // approval — so a mis-encoded session/request id shows up here at send time.
    // NB: the callback *URL* (where Slack POSTs the click) is the Slack app's
    // interactivity request_url from the manifest, not anything we send here.
    opts.logger?.info?.(
        {
            session_id: opts.sessionId,
            request_id: opts.requestId,
            channel: opts.channel,
            thread_ts: opts.thread_ts,
            tool_name: opts.toolName,
            approve_value: value('approve'),
            reject_value: value('reject'),
        },
        'slack_approval_buttons_post'
    )
    try {
        const res = await http.fetch('https://slack.com/api/chat.postMessage', {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${opts.token}`,
                'Content-Type': 'application/json; charset=utf-8',
            },
            body: JSON.stringify({
                channel: opts.channel,
                thread_ts: opts.thread_ts,
                text: `Approval needed for ${opts.toolName}`,
                blocks,
            }),
        })
        let body: { ok?: boolean; error?: string } = {}
        try {
            body = (await res.json()) as { ok?: boolean; error?: string }
        } catch {
            // Non-JSON — fall through to the res.ok check.
        }
        if (!res.ok || body.ok === false) {
            opts.logger?.warn(
                {
                    session_id: opts.sessionId,
                    channel: opts.channel,
                    status: res.status,
                    slack_error: body.error ?? null,
                },
                'slack_approval_buttons_failed'
            )
            return false
        }
        return true
    } catch (err) {
        opts.logger?.warn(
            {
                session_id: opts.sessionId,
                channel: opts.channel,
                err: err instanceof Error ? err.message : String(err),
            },
            'slack_approval_buttons_threw'
        )
        return false
    }
}

export async function postSlackReply(http: HttpFetcher, opts: PostSlackReplyOpts): Promise<boolean> {
    // The model replies in Markdown; Slack speaks mrkdwn.
    const text = markdownToMrkdwn(opts.text).trim()
    if (!text) {
        return false
    }
    if (!opts.token) {
        opts.logger?.warn({ session_id: opts.sessionId, channel: opts.channel }, 'slack_reply_no_bot_token')
        return false
    }
    try {
        const res = await http.fetch('https://slack.com/api/chat.postMessage', {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${opts.token}`,
                'Content-Type': 'application/json; charset=utf-8',
            },
            body: JSON.stringify({ channel: opts.channel, thread_ts: opts.thread_ts, text }),
        })
        let body: { ok?: boolean; error?: string } = {}
        try {
            body = (await res.json()) as { ok?: boolean; error?: string }
        } catch {
            // Non-JSON response — fall through to the res.ok check below.
        }
        if (!res.ok || body.ok === false) {
            opts.logger?.warn(
                {
                    session_id: opts.sessionId,
                    channel: opts.channel,
                    thread_ts: opts.thread_ts,
                    status: res.status,
                    slack_error: body.error ?? null,
                },
                'slack_reply_post_failed'
            )
            return false
        }
        return true
    } catch (err) {
        opts.logger?.warn(
            {
                session_id: opts.sessionId,
                channel: opts.channel,
                err: err instanceof Error ? err.message : String(err),
            },
            'slack_reply_post_threw'
        )
        return false
    }
}
