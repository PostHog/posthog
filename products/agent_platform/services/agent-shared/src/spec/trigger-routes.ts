/**
 * Per-trigger-type ingress route catalogue. Single source shared by agent-ingress
 * (each trigger module imports its `path:` values from here) and Django's
 * preview-endpoint builder (via the generated artifact), so the routes can't drift.
 * `cron` maps to `{}` — janitor-fired, no inbound route. `Record<TriggerType, …>`
 * is total: a new trigger type without an entry here fails to compile.
 */

import type { TriggerType } from './spec'

export const TRIGGER_ROUTES: Record<TriggerType, Record<string, string>> = {
    chat: {
        run: '/run',
        send: '/send',
        cancel: '/cancel',
        listen: '/listen',
        client_tool_result: '/client_tool_result',
    },
    slack: {
        events: '/slack/events',
        interactivity: '/slack/interactivity',
    },
    cron: {},
    webhook: {
        post: '/webhook',
    },
    mcp: {
        rpc: '/mcp',
        stream: '/mcp/stream',
        connect_info: '/mcp/connect-info',
    },
}
