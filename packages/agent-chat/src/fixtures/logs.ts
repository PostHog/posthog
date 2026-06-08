/**
 * Sample platform log entries for a session.
 *
 * Shape mirrors the real PostHog logs product row (level / service /
 * message / structured fields) so v0.1 swaps the fixture for a real
 * logs-query result without consumer changes.
 *
 * Source-of-truth in real life: the runner, ingress, and janitor all
 * pino-log with a `session_id` field on every entry. PostHog's logs
 * product queries by `session_id = X` to give the per-session trace
 * the console renders here.
 */

import { incidentTriager, releaseConcierge, weeklyDigest } from './agents'

export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'fatal'

export interface LogEntry {
    /** ISO timestamp. */
    ts: string
    level: LogLevel
    /** Originating service: `runner` · `ingress` · `janitor` · `sandbox`. */
    service: string
    message: string
    /** Structured fields the runner attaches (call_id, tool_id, latency_ms, etc.). */
    fields?: Record<string, unknown>
}

/* ── Per-session log fixtures ────────────────────────────────────── */

/** Logs for the most recent weekly-digest manual test run (`...0007d2`). */
const weeklyDigestTestRunLogs: LogEntry[] = [
    {
        ts: '2026-05-27T17:11:00.040Z',
        level: 'info',
        service: 'ingress',
        message: 'chat trigger accepted',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d2',
            application_id: weeklyDigest.id,
            revision_id: '01998a01-1111-7000-8000-000000000a01',
            principal: 'ben@posthog.com',
        },
    },
    {
        ts: '2026-05-27T17:11:00.118Z',
        level: 'info',
        service: 'runner',
        message: 'session claimed',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d2',
            queue_wait_ms: 78,
        },
    },
    {
        ts: '2026-05-27T17:11:00.412Z',
        level: 'info',
        service: 'runner',
        message: 'model.generate start',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d2',
            model: 'anthropic/claude-sonnet-4-6',
            turn: 1,
        },
    },
    {
        ts: '2026-05-27T17:11:08.244Z',
        level: 'info',
        service: 'runner',
        message: 'model.generate ok',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d2',
            input_tokens: 482,
            output_tokens: 87,
            latency_ms: 7832,
            cost_usd: 0.0042,
        },
    },
    {
        ts: '2026-05-27T17:11:08.301Z',
        level: 'info',
        service: 'runner',
        message: 'tool.dispatch',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d2',
            tool_id: '@posthog/query',
            call_id: 'call-h2-q1',
            args_size_bytes: 184,
        },
    },
    {
        ts: '2026-05-27T17:11:09.847Z',
        level: 'info',
        service: 'runner',
        message: 'tool.result',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d2',
            tool_id: '@posthog/query',
            call_id: 'call-h2-q1',
            ok: true,
            latency_ms: 1546,
            result_size_bytes: 1240,
        },
    },
    {
        ts: '2026-05-27T17:11:09.901Z',
        level: 'info',
        service: 'runner',
        message: 'model.generate start',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d2',
            model: 'anthropic/claude-sonnet-4-6',
            turn: 2,
        },
    },
    {
        ts: '2026-05-27T17:11:38.122Z',
        level: 'info',
        service: 'runner',
        message: 'model.generate ok',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d2',
            input_tokens: 758,
            output_tokens: 231,
            latency_ms: 28221,
            cost_usd: 0.0368,
        },
    },
    {
        ts: '2026-05-27T17:11:38.198Z',
        level: 'info',
        service: 'runner',
        message: 'session.completed',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d2',
            total_turns: 2,
            total_tool_calls: 1,
            duration_ms: 38158,
            cost_usd: 0.041,
        },
    },
]

/** Logs for the weekly-digest failed manual run (`...0007d3`) — short, ends in error. */
const weeklyDigestFailedRunLogs: LogEntry[] = [
    {
        ts: '2026-05-26T22:48:00.022Z',
        level: 'info',
        service: 'ingress',
        message: 'chat trigger accepted',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d3',
            application_id: weeklyDigest.id,
            principal: 'ben@posthog.com',
        },
    },
    {
        ts: '2026-05-26T22:48:00.198Z',
        level: 'info',
        service: 'runner',
        message: 'session claimed',
        fields: { session_id: '01998a01-2222-7000-8000-0000000007d3' },
    },
    {
        ts: '2026-05-26T22:48:00.541Z',
        level: 'info',
        service: 'runner',
        message: 'tool.dispatch',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d3',
            tool_id: '@posthog/query',
            call_id: 'call-h3-q1',
        },
    },
    {
        ts: '2026-05-26T22:48:04.812Z',
        level: 'warn',
        service: 'runner',
        message: 'tool.error',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d3',
            tool_id: '@posthog/query',
            call_id: 'call-h3-q1',
            error: 'ClickHouse returned 502 — DB_NET_EXCEPTION',
            retryable: true,
        },
    },
    {
        ts: '2026-05-26T22:48:08.991Z',
        level: 'info',
        service: 'runner',
        message: 'tool.retry',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d3',
            tool_id: '@posthog/query',
            call_id: 'call-h3-q1',
            attempt: 2,
        },
    },
    {
        ts: '2026-05-26T22:48:11.487Z',
        level: 'error',
        service: 'runner',
        message: 'tool.error',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d3',
            tool_id: '@posthog/query',
            call_id: 'call-h3-q1',
            error: 'ClickHouse returned 502 — DB_NET_EXCEPTION',
            retryable: false,
            attempts: 2,
        },
    },
    {
        ts: '2026-05-26T22:48:12.013Z',
        level: 'error',
        service: 'runner',
        message: 'session.failed',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007d3',
            reason: 'Tool `@posthog/query` returned 502 from ClickHouse twice in a row.',
            duration_ms: 11991,
        },
    },
]

/** Live cron-firing logs for the in-flight weekly-digest streaming session. */
const weeklyDigestStreamingLogs: LogEntry[] = [
    {
        ts: '2026-05-28T15:55:00.012Z',
        level: 'info',
        service: 'janitor',
        message: 'cron.fired',
        fields: {
            session_id: '01998a01-2222-7000-8000-000000000002',
            schedule: '0 9 * * MON',
            application_id: weeklyDigest.id,
        },
    },
    {
        ts: '2026-05-28T15:55:00.301Z',
        level: 'info',
        service: 'runner',
        message: 'session claimed',
        fields: { session_id: '01998a01-2222-7000-8000-000000000002' },
    },
    {
        ts: '2026-05-28T15:55:01.118Z',
        level: 'info',
        service: 'runner',
        message: 'model.generate start',
        fields: {
            session_id: '01998a01-2222-7000-8000-000000000002',
            model: 'anthropic/claude-sonnet-4-6',
            turn: 1,
        },
    },
    {
        ts: '2026-05-28T15:55:02.041Z',
        level: 'debug',
        service: 'runner',
        message: 'sse.delta',
        fields: {
            session_id: '01998a01-2222-7000-8000-000000000002',
            kind: 'text',
            chars: 24,
        },
    },
]

/** Release-concierge awaiting approval. */
const releaseAwaitingLogs: LogEntry[] = [
    {
        ts: '2026-05-28T15:38:00.121Z',
        level: 'info',
        service: 'ingress',
        message: 'chat trigger accepted',
        fields: {
            session_id: '01998a01-2222-7000-8000-000000000102',
            application_id: releaseConcierge.id,
            principal: 'ari@posthog.com',
        },
    },
    {
        ts: '2026-05-28T15:38:08.391Z',
        level: 'info',
        service: 'runner',
        message: 'tool.dispatch',
        fields: {
            session_id: '01998a01-2222-7000-8000-000000000102',
            tool_id: 'github.pull_request_open',
            call_id: 'fleet-call-1',
            requires_approval: true,
        },
    },
    {
        ts: '2026-05-28T15:38:08.422Z',
        level: 'info',
        service: 'runner',
        message: 'approval.requested',
        fields: {
            session_id: '01998a01-2222-7000-8000-000000000102',
            tool_id: 'github.pull_request_open',
            call_id: 'fleet-call-1',
            approvers: ['session_owner', 'team_members'],
        },
    },
    {
        ts: '2026-05-28T15:38:08.501Z',
        level: 'info',
        service: 'runner',
        message: 'session.suspended',
        fields: {
            session_id: '01998a01-2222-7000-8000-000000000102',
            reason: 'awaiting_user_input',
        },
    },
]

/** Release-concierge slack-triggered Q&A about a past release. */
const releaseSlackQuestionLogs: LogEntry[] = [
    {
        ts: '2026-05-24T10:20:00.041Z',
        level: 'info',
        service: 'ingress',
        message: 'slack.event received',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007e2',
            application_id: releaseConcierge.id,
            workspace: 'PostHog',
            channel: 'product-eng',
            thread_ts: '1748120400.001050',
            event_type: 'app_mention',
        },
    },
    {
        ts: '2026-05-24T10:20:00.187Z',
        level: 'info',
        service: 'runner',
        message: 'session claimed',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007e2',
            principal: 'slack:U03DYLAN',
        },
    },
    {
        ts: '2026-05-24T10:20:01.092Z',
        level: 'info',
        service: 'runner',
        message: 'tool.dispatch',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007e2',
            tool_id: 'github.releases.show',
            call_id: 'call-rh2-r1',
            args: { tag: 'v2.39' },
        },
    },
    {
        ts: '2026-05-24T10:20:02.418Z',
        level: 'info',
        service: 'runner',
        message: 'tool.result',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007e2',
            tool_id: 'github.releases.show',
            call_id: 'call-rh2-r1',
            ok: true,
            latency_ms: 1326,
        },
    },
    {
        ts: '2026-05-24T10:20:08.012Z',
        level: 'info',
        service: 'runner',
        message: 'tool.dispatch',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007e2',
            tool_id: '@posthog/slack-post-message',
            call_id: 'call-rh2-s1',
            channel: 'product-eng',
            thread_ts: '1748120400.001050',
        },
    },
    {
        ts: '2026-05-24T10:20:08.520Z',
        level: 'info',
        service: 'runner',
        message: 'tool.result',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007e2',
            tool_id: '@posthog/slack-post-message',
            call_id: 'call-rh2-s1',
            ok: true,
            latency_ms: 508,
        },
    },
    {
        ts: '2026-05-24T10:20:48.041Z',
        level: 'info',
        service: 'runner',
        message: 'session.completed',
        fields: {
            session_id: '01998a01-2222-7000-8000-0000000007e2',
            total_turns: 2,
            total_tool_calls: 2,
            duration_ms: 48000,
            cost_usd: 0.082,
        },
    },
]

/** Incident-triager streaming. */
const triagerStreamingLogs: LogEntry[] = [
    {
        ts: '2026-05-28T15:52:00.041Z',
        level: 'info',
        service: 'ingress',
        message: 'webhook.received',
        fields: {
            session_id: '01998a01-2222-7000-8000-000000000103',
            application_id: incidentTriager.id,
            path: '/incidents/triage',
            source: 'pagerduty',
        },
    },
    {
        ts: '2026-05-28T15:52:00.421Z',
        level: 'info',
        service: 'runner',
        message: 'session claimed',
        fields: {
            session_id: '01998a01-2222-7000-8000-000000000103',
            queue_wait_ms: 380,
        },
    },
    {
        ts: '2026-05-28T15:52:03.122Z',
        level: 'info',
        service: 'runner',
        message: 'model.generate start',
        fields: {
            session_id: '01998a01-2222-7000-8000-000000000103',
            model: 'anthropic/claude-haiku-4-5',
            turn: 1,
        },
    },
]

/** Map of `session_id` → log fixtures. Sessions without an entry render an empty log pane. */
const LOGS_BY_SESSION: Record<string, LogEntry[]> = {
    '01998a01-2222-7000-8000-0000000007d2': weeklyDigestTestRunLogs,
    '01998a01-2222-7000-8000-0000000007d3': weeklyDigestFailedRunLogs,
    '01998a01-2222-7000-8000-0000000007e2': releaseSlackQuestionLogs,
    '01998a01-2222-7000-8000-000000000002': weeklyDigestStreamingLogs,
    '01998a01-2222-7000-8000-000000000102': releaseAwaitingLogs,
    '01998a01-2222-7000-8000-000000000103': triagerStreamingLogs,
}

export function listLogsForSessionFixture(sessionId: string): LogEntry[] {
    const list = LOGS_BY_SESSION[sessionId] ?? []
    return [...list].sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime())
}

/** Convenience export so stories can grab a known-good non-empty fixture. */
export const sampleSessionLogs = weeklyDigestTestRunLogs
