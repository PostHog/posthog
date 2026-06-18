import {
    defineNativeTool,
    HttpFetcher,
    isPreviewSideEffect,
    SLACK_BOT_TOKEN_KEY,
    ToolContext,
    Type,
} from '@posthog/agent-shared'

/**
 * Resolve the agent's Slack bot token from `encrypted_env` via `ctx.secret`.
 * Per-app, not per-team — `SLACK_BOT_TOKEN_KEY` is registered as a
 * trigger-required secret for `slack` triggers (see `trigger-secrets.ts`),
 * so the freeze + promote gate refuses revisions whose application doesn't
 * have it set. Tools throw a precise error rather than a generic 401 so the
 * model sees what's missing.
 */
function slackBotToken(ctx: ToolContext): string {
    const token = ctx.secret(SLACK_BOT_TOKEN_KEY)
    if (!token) {
        throw new Error(
            `slack bot token missing — set ${SLACK_BOT_TOKEN_KEY} on this agent (Settings → Install App → Bot User OAuth Token in your Slack app dashboard)`
        )
    }
    return token
}

async function slackCall(
    http: HttpFetcher,
    token: string,
    method: string,
    body: Record<string, unknown>
): Promise<unknown> {
    const res = await http.fetch(`https://slack.com/api/${method}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json; charset=utf-8',
            Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(body),
    })
    if (!res.ok) {
        throw new Error(`slack.${method} HTTP ${res.status}`)
    }
    const j = (await res.json()) as { ok: boolean; error?: string }
    if (!j.ok) {
        throw new Error(`slack.${method} error: ${j.error ?? 'unknown'}`)
    }
    return j
}

interface RawSlackMessage {
    ts?: string
    user?: string
    bot_id?: string
    username?: string
    text?: string
    type?: string
    subtype?: string
    thread_ts?: string
    reply_count?: number
}

const SlackMessageSchema = Type.Object({
    ts: Type.String(),
    user: Type.Optional(Type.String()),
    bot_id: Type.Optional(Type.String()),
    username: Type.Optional(Type.String()),
    text: Type.String(),
    subtype: Type.Optional(Type.String()),
    thread_ts: Type.Optional(Type.String()),
    reply_count: Type.Optional(Type.Number()),
})

function projectMessage(m: RawSlackMessage): {
    ts: string
    user?: string
    bot_id?: string
    username?: string
    text: string
    subtype?: string
    thread_ts?: string
    reply_count?: number
} {
    return {
        ts: m.ts ?? '',
        user: m.user,
        bot_id: m.bot_id,
        username: m.username,
        text: m.text ?? '',
        subtype: m.subtype,
        thread_ts: m.thread_ts,
        reply_count: m.reply_count,
    }
}

export const slackPostMessageV1 = defineNativeTool({
    id: '@posthog/slack-post-message',
    description: "Post a message to a Slack channel or thread using the agent's bot token.",
    args: Type.Object({
        channel: Type.String(),
        text: Type.String(),
        thread_ts: Type.Optional(Type.String()),
    }),
    returns: Type.Object({
        ts: Type.String(),
        channel: Type.String(),
    }),
    requires: { scopes: ['chat:write'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        // Preview-mode noop: don't post into the real channel attached to the
        // live revision while the author is iterating. The synthetic `ts` is
        // shape-valid so a follow-up `slack-update-message` / `slack-react`
        // in the same preview turn doesn't blow up on a missing ts — though
        // those write tools also short-circuit on preview, so the synthetic
        // value never reaches slack.com regardless.
        if (isPreviewSideEffect(ctx, '@posthog/slack-post-message', args)) {
            return { ts: `preview-noop:${Date.now()}`, channel: args.channel }
        }
        const token = slackBotToken(ctx)
        const res = (await slackCall(ctx.http, token, 'chat.postMessage', {
            channel: args.channel,
            text: args.text,
            thread_ts: args.thread_ts,
        })) as { ts: string; channel: string }
        return { ts: res.ts, channel: res.channel }
    },
})

export const slackUpdateMessageV1 = defineNativeTool({
    id: '@posthog/slack-update-message',
    description: 'Edit a previously-posted Slack message.',
    args: Type.Object({
        channel: Type.String(),
        ts: Type.String(),
        text: Type.String(),
    }),
    returns: Type.Object({ ok: Type.Boolean() }),
    requires: { scopes: ['chat:write'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        if (isPreviewSideEffect(ctx, '@posthog/slack-update-message', args)) {
            return { ok: true }
        }
        const token = slackBotToken(ctx)
        await slackCall(ctx.http, token, 'chat.update', { channel: args.channel, ts: args.ts, text: args.text })
        return { ok: true }
    },
})

export const slackReadChannelV1 = defineNativeTool({
    id: '@posthog/slack-read-channel',
    description:
        'Read recent messages from a Slack channel. Returns top-level messages only (use @posthog/slack-read-thread for replies). Paginate with next_cursor; narrow with oldest/latest (slack ts).',
    args: Type.Object({
        channel: Type.String(),
        limit: Type.Optional(Type.Number()),
        oldest: Type.Optional(Type.String()),
        latest: Type.Optional(Type.String()),
        cursor: Type.Optional(Type.String()),
    }),
    returns: Type.Object({
        messages: Type.Array(SlackMessageSchema),
        has_more: Type.Boolean(),
        next_cursor: Type.Optional(Type.String()),
    }),
    requires: { scopes: ['channels:history', 'groups:history'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const token = slackBotToken(ctx)
        const limit = Math.min(Math.max(args.limit ?? 50, 1), 200)
        const body: Record<string, unknown> = { channel: args.channel, limit }
        if (args.oldest) {
            body.oldest = args.oldest
        }
        if (args.latest) {
            body.latest = args.latest
        }
        if (args.cursor) {
            body.cursor = args.cursor
        }
        const res = (await slackCall(ctx.http, token, 'conversations.history', body)) as {
            messages?: RawSlackMessage[]
            has_more?: boolean
            response_metadata?: { next_cursor?: string }
        }
        const nextCursor = res.response_metadata?.next_cursor
        return {
            messages: (res.messages ?? []).map(projectMessage),
            has_more: Boolean(res.has_more),
            next_cursor: nextCursor && nextCursor.length > 0 ? nextCursor : undefined,
        }
    },
})

export const slackReadThreadV1 = defineNativeTool({
    id: '@posthog/slack-read-thread',
    description: 'Read a Slack thread — the parent message plus all replies. thread_ts is the parent message ts.',
    args: Type.Object({
        channel: Type.String(),
        thread_ts: Type.String(),
        limit: Type.Optional(Type.Number()),
        cursor: Type.Optional(Type.String()),
    }),
    returns: Type.Object({
        messages: Type.Array(SlackMessageSchema),
        has_more: Type.Boolean(),
        next_cursor: Type.Optional(Type.String()),
    }),
    requires: { scopes: ['channels:history', 'groups:history'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const token = slackBotToken(ctx)
        const limit = Math.min(Math.max(args.limit ?? 50, 1), 200)
        const body: Record<string, unknown> = {
            channel: args.channel,
            ts: args.thread_ts,
            limit,
        }
        if (args.cursor) {
            body.cursor = args.cursor
        }
        const res = (await slackCall(ctx.http, token, 'conversations.replies', body)) as {
            messages?: RawSlackMessage[]
            has_more?: boolean
            response_metadata?: { next_cursor?: string }
        }
        const nextCursor = res.response_metadata?.next_cursor
        return {
            messages: (res.messages ?? []).map(projectMessage),
            has_more: Boolean(res.has_more),
            next_cursor: nextCursor && nextCursor.length > 0 ? nextCursor : undefined,
        }
    },
})

export const slackReactV1 = defineNativeTool({
    id: '@posthog/slack-react',
    description: 'Add an emoji reaction to a Slack message.',
    args: Type.Object({
        channel: Type.String(),
        ts: Type.String(),
        name: Type.String(),
    }),
    returns: Type.Object({ ok: Type.Boolean() }),
    requires: { scopes: ['reactions:write'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        if (isPreviewSideEffect(ctx, '@posthog/slack-react', args)) {
            return { ok: true }
        }
        const token = slackBotToken(ctx)
        await slackCall(ctx.http, token, 'reactions.add', {
            channel: args.channel,
            timestamp: args.ts,
            name: args.name,
        })
        return { ok: true }
    },
})
