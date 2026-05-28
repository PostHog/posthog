/**
 * Mock chat sessions covering the visual states `<AgentChat />` needs to render.
 *
 * Each fixture is a fully-formed `ChatSession` — no live transport, no
 * partial assembly. Stories pick one as a static prop and the component
 * renders it. v0.2 will swap this for a real session driven by SSE.
 */

import type { ChatSession, ClientToolHandler, FocusArgs, FocusResult, PendingApproval, ToastArgs, ToastResult, Turn } from '../types'
import { incidentTriager, releaseConcierge, weeklyDigest } from './agents'

const principal = {
    kind: 'human' as const,
    userId: '1',
    displayName: 'Ben White',
}

const baseUsage = { inputTokens: 0, outputTokens: 0, costUsd: 0 }

const empty: Turn[] = []

const greetingExchange: Turn[] = [
    {
        kind: 'user',
        id: 'turn-001',
        timestamp: '2026-05-28T14:00:00Z',
        text: "Hi! I want to add a GitHub PRs callout to the weekly digest. Can you set that up?",
    },
    {
        kind: 'assistant',
        id: 'turn-002',
        timestamp: '2026-05-28T14:00:04Z',
        parts: [
            {
                kind: 'thinking',
                text: "I'll branch a draft from the live revision, then add a github-search tool and a callout skill.",
            },
            {
                kind: 'text',
                text: 'On it. I just branched a fresh draft from the current live revision (`01998a01…1a01`). Let me pull the bundle so I can see what skills already exist.',
            },
            {
                kind: 'tool_call',
                toolId: 'agent-applications-revisions-new-draft-create',
                callId: 'call-001',
                fulfillment: 'server',
                args: { application_id: '01998a01-1111-7000-8000-000000000001' },
                result: {
                    ok: true,
                    body: {
                        revision: { id: '01998a01-1111-7000-8000-000000000a02', state: 'draft' },
                    },
                },
            },
            {
                kind: 'tool_call',
                toolId: '@posthog/ui/focus',
                callId: 'call-002',
                fulfillment: 'client',
                args: { kind: 'revision', revisionId: '01998a01-1111-7000-8000-000000000a02' },
                result: { ok: true, body: { focused: true, kind: 'revision' } },
            },
        ],
    },
]

const streamingMid: Turn[] = [
    ...greetingExchange,
    {
        kind: 'assistant',
        id: 'turn-003',
        timestamp: '2026-05-28T14:00:18Z',
        streaming: true,
        parts: [
            {
                kind: 'thinking',
                text: 'The current bundle has digest-shape.md but no PR-related skill. I need to add one and wire it into the spec.',
            },
            {
                kind: 'text',
                text: 'I see the bundle has a `digest-shape` skill but nothing about PRs yet. I',
            },
        ],
    },
]

const awaitingFocusCall: Turn[] = [
    ...greetingExchange,
    {
        kind: 'assistant',
        id: 'turn-003b',
        timestamp: '2026-05-28T14:00:20Z',
        streaming: true,
        parts: [
            {
                kind: 'text',
                text: "Let me show you the new skill before I freeze the draft.",
            },
            {
                kind: 'tool_call',
                toolId: '@posthog/ui/focus',
                callId: 'call-003',
                fulfillment: 'client',
                args: { kind: 'file', path: 'skills/pr-callouts.md' },
                // No result yet — the client is still handling the call.
            },
        ],
    },
]

const awaitingApproval: PendingApproval[] = [
    {
        callId: 'call-004',
        toolId: 'agent-applications-revisions-promote-create',
        args: {
            application_id: '01998a01-1111-7000-8000-000000000001',
            revision_id: '01998a01-1111-7000-8000-000000000a02',
        },
        requestedAt: '2026-05-28T14:01:00Z',
    },
]

const richExchangeForApproval: Turn[] = [
    ...greetingExchange,
    {
        kind: 'assistant',
        id: 'turn-004',
        timestamp: '2026-05-28T14:00:45Z',
        parts: [
            {
                kind: 'text',
                text: 'I added the `pr-callouts` skill and wired `@posthog/github-search` into the spec. I ran the test suite — all 3 cases pass. Ready to promote when you give the word.',
            },
            {
                kind: 'tool_call',
                toolId: 'agent-applications-revisions-promote-create',
                callId: 'call-004',
                fulfillment: 'server',
                args: {
                    application_id: '01998a01-1111-7000-8000-000000000001',
                    revision_id: '01998a01-1111-7000-8000-000000000a02',
                },
            },
        ],
    },
]

export const idleSession: ChatSession = {
    id: '01998a01-2222-7000-8000-000000000001',
    application: weeklyDigest,
    principal,
    turns: empty,
    state: 'idle',
    pendingApprovals: [],
    usage: baseUsage,
}

export const streamingSession: ChatSession = {
    id: '01998a01-2222-7000-8000-000000000002',
    application: weeklyDigest,
    principal,
    turns: streamingMid,
    state: 'streaming',
    pendingApprovals: [],
    usage: { inputTokens: 1240, outputTokens: 384, costUsd: 0.012 },
}

export const awaitingClientToolSession: ChatSession = {
    id: '01998a01-2222-7000-8000-000000000003',
    application: weeklyDigest,
    principal,
    turns: awaitingFocusCall,
    state: 'awaiting_client_tool',
    pendingApprovals: [],
    usage: { inputTokens: 1240, outputTokens: 412, costUsd: 0.013 },
}

export const awaitingApprovalSession: ChatSession = {
    id: '01998a01-2222-7000-8000-000000000004',
    application: weeklyDigest,
    principal,
    turns: richExchangeForApproval,
    state: 'awaiting_approval',
    pendingApprovals: awaitingApproval,
    usage: { inputTokens: 4827, outputTokens: 1102, costUsd: 0.041 },
}

export const disconnectedSession: ChatSession = {
    id: '01998a01-2222-7000-8000-000000000005',
    application: weeklyDigest,
    principal,
    turns: greetingExchange,
    state: 'disconnected',
    pendingApprovals: [],
    usage: { inputTokens: 1240, outputTokens: 384, costUsd: 0.012 },
}

export const erroredSession: ChatSession = {
    id: '01998a01-2222-7000-8000-000000000006',
    application: weeklyDigest,
    principal,
    turns: greetingExchange,
    state: 'error',
    pendingApprovals: [],
    usage: { inputTokens: 1240, outputTokens: 384, costUsd: 0.012 },
    error: 'Upstream model rate-limited. Retrying in 15s.',
}

/** Empty session — used everywhere the dock is showing its waiting state. */
export const waitingSession: ChatSession = {
    id: '01998a01-2222-7000-8000-000000000007',
    application: weeklyDigest,
    principal,
    turns: empty,
    state: 'idle',
    pendingApprovals: [],
    usage: baseUsage,
}

/**
 * A playground-mode exchange: the user talks to the agent directly
 * (no concierge in the middle), so turns are about the agent's
 * *output*, not its configuration.
 */
const playgroundExchange: Turn[] = [
    {
        kind: 'user',
        id: 'pg-001',
        timestamp: '2026-05-28T15:10:00Z',
        text: 'Pretend it’s Monday morning. Run for last week.',
    },
    {
        kind: 'assistant',
        id: 'pg-002',
        timestamp: '2026-05-28T15:10:06Z',
        parts: [
            {
                kind: 'tool_call',
                toolId: '@posthog/query',
                callId: 'pg-call-1',
                fulfillment: 'server',
                args: { hogql: "select event, count() from events where timestamp > now() - interval 7 day group by event order by 2 desc limit 5" },
                result: {
                    ok: true,
                    body: [
                        ['$pageview', 18420],
                        ['$autocapture', 9112],
                        ['agent_session_started', 312],
                    ],
                },
            },
            {
                kind: 'text',
                text:
                    'Top events last week:\n\n• $pageview — 18.4k\n• $autocapture — 9.1k\n• agent_session_started — 312\n\nWant the digest posted to #product-eng, or a dry-run first?',
            },
        ],
    },
]

export const playgroundSession: ChatSession = {
    id: '01998a01-2222-7000-8000-000000000008',
    application: weeklyDigest,
    trigger: { kind: 'chat' },
    principal,
    turns: playgroundExchange,
    state: 'idle',
    pendingApprovals: [],
    usage: { inputTokens: 412, outputTokens: 188, costUsd: 0.004 },
}

export const allSessionStates = {
    waiting: waitingSession,
    idle: idleSession,
    streaming: streamingSession,
    awaitingClientTool: awaitingClientToolSession,
    awaitingApproval: awaitingApprovalSession,
    disconnected: disconnectedSession,
    errored: erroredSession,
    playground: playgroundSession,
} as const

/* ──────────────────────────────────────────────────────────────────────────
 * Fleet-level fixtures — sessions spanning multiple agents, used by the
 * agents-list "live now" panel and any future cross-agent sessions view.
 *
 * These are minimal — just enough to populate a fleet list. Tasks are
 * paraphrased plausible work; states cover idle / streaming /
 * awaiting_approval so the visual variety reads.
 * ──────────────────────────────────────────────────────────────────────── */

function aliceTurn(text: string, at: string): Turn {
    return { kind: 'user', id: `u-${at}`, timestamp: at, text }
}

const releaseStreamingSession: ChatSession = {
    id: '01998a01-2222-7000-8000-000000000101',
    application: releaseConcierge,
    trigger: { kind: 'cron', schedule: '0 16 * * THU', timezone: 'UTC', firedAt: '2026-05-28T15:46:00Z' },
    principal: { kind: 'system', displayName: 'cron · weekly cut' },
    turns: [
        aliceTurn('Cut the v2.41 release. PR for the changelog, ping owners on any failing checks.', '2026-05-28T15:46:00Z'),
        {
            kind: 'assistant',
            id: 'a-1',
            timestamp: '2026-05-28T15:46:02Z',
            streaming: true,
            parts: [
                {
                    kind: 'text',
                    text: 'Drafting the changelog from the last 24 merged PRs…',
                },
            ],
        },
    ],
    state: 'streaming',
    pendingApprovals: [],
    usage: { inputTokens: 2410, outputTokens: 612, costUsd: 0.087 },
    started_at: '2026-05-28T15:46:00Z',
}

const releaseAwaitingSession: ChatSession = {
    id: '01998a01-2222-7000-8000-000000000102',
    application: releaseConcierge,
    trigger: {
        kind: 'slack',
        workspace: 'PostHog',
        channelId: 'C012XYZ',
        channelName: 'product-eng',
        threadTs: '1748452680.001200',
        rootMessage: '@release-concierge hotfix the timezone bug in v2.40 please',
        invokedBy: 'Ari',
    },
    principal: { kind: 'human', userId: '2', displayName: 'Ari' },
    turns: [
        aliceTurn('Hotfix the timezone bug in v2.40.', '2026-05-28T15:38:00Z'),
        {
            kind: 'assistant',
            id: 'a-2',
            timestamp: '2026-05-28T15:38:08Z',
            parts: [
                {
                    kind: 'text',
                    text: 'Patch is ready. Opening a PR against `release/2.40` — needs your approval to push.',
                },
            ],
        },
    ],
    state: 'awaiting_approval',
    pendingApprovals: [
        {
            callId: 'fleet-call-1',
            toolId: 'github.pull_request_open',
            args: { repo: 'posthog/posthog', base: 'release/2.40', head: 'hotfix/tz-2.40' },
            requestedAt: '2026-05-28T15:38:30Z',
        },
    ],
    usage: { inputTokens: 1820, outputTokens: 487, costUsd: 0.064 },
    started_at: '2026-05-28T15:38:00Z',
}

const triagerStreamingSession: ChatSession = {
    id: '01998a01-2222-7000-8000-000000000103',
    application: incidentTriager,
    trigger: { kind: 'webhook', path: '/incidents/triage', source: 'pagerduty' },
    principal: { kind: 'system', displayName: 'pagerduty · INC-4112' },
    turns: [
        aliceTurn('INC-4112 fired: ingest p99 > 5s in prod-eu. Triage.', '2026-05-28T15:52:00Z'),
        {
            kind: 'assistant',
            id: 'a-3',
            timestamp: '2026-05-28T15:52:03Z',
            streaming: true,
            parts: [
                {
                    kind: 'text',
                    text: 'Looking at the last 30 minutes of deploys and Kafka lag in prod-eu',
                },
            ],
        },
    ],
    state: 'streaming',
    pendingApprovals: [],
    usage: { inputTokens: 980, outputTokens: 218, costUsd: 0.029 },
    started_at: '2026-05-28T15:52:00Z',
}

const digestActiveSession: ChatSession = {
    ...idleSession,
    state: 'streaming',
    trigger: { kind: 'cron', schedule: '0 9 * * MON', timezone: 'US/Pacific', firedAt: '2026-05-28T15:55:00Z' },
    started_at: '2026-05-28T15:55:00Z',
    turns: [
        aliceTurn('Test run for the digest draft', '2026-05-28T15:55:00Z'),
        {
            kind: 'assistant',
            id: 'a-4',
            timestamp: '2026-05-28T15:55:02Z',
            streaming: true,
            parts: [{ kind: 'text', text: 'Pulling last week’s top events…' }],
        },
    ],
    usage: { inputTokens: 412, outputTokens: 78, costUsd: 0.008 },
}

/**
 * All currently-live sessions across the fleet, newest first.
 * v0.2 will derive this from `GET /api/projects/:t/agent_sessions/?state=live`.
 */
export const fleetLiveSessions: ChatSession[] = [
    triagerStreamingSession,
    digestActiveSession,
    releaseStreamingSession,
    releaseAwaitingSession,
]

/**
 * Fleet-level rollup stats. Numbers chosen to look plausible against the
 * fixtures above; v0.1 will swap for real aggregates from the REST API.
 */
export interface FleetStats {
    liveSessionCount: number
    sessions24hCount: number
    spend24hUsd: number
    approvalsPendingCount: number
}

export const fleetStats: FleetStats = {
    liveSessionCount: 4,
    sessions24hCount: 87,
    spend24hUsd: 12.43,
    approvalsPendingCount: 1,
}

/** Per-agent live session counts, keyed by application id. */
export const liveSessionCountsByAgent: Record<string, number> = {
    [weeklyDigest.id]: 1,
    [releaseConcierge.id]: 2,
    [incidentTriager.id]: 1,
}

/* ──────────────────────────────────────────────────────────────────────────
 * Per-agent historical sessions — cover the past 24-48h so the per-agent
 * Sessions tab on the detail page has something to render. Mix of
 * completed/failed/live states.
 *
 * v0.1 wires `GET /api/projects/:t/agent_applications/<id>/sessions/`.
 * ──────────────────────────────────────────────────────────────────────── */

function makeHistorical(
    overrides: Partial<ChatSession> & Pick<ChatSession, 'id' | 'application' | 'state' | 'started_at' | 'ended_at'>
): ChatSession {
    return {
        principal,
        turns: [],
        pendingApprovals: [],
        usage: { inputTokens: 0, outputTokens: 0, costUsd: 0 },
        ...overrides,
    }
}

const weeklyDigestHistory: ChatSession[] = [
    digestActiveSession, // already defined above (state: 'streaming')
    makeHistorical({
        id: '01998a01-2222-7000-8000-0000000007d1',
        application: weeklyDigest,
        trigger: { kind: 'cron', schedule: '0 9 * * MON', timezone: 'US/Pacific', firedAt: '2026-05-27T09:00:00-07:00' },
        principal: { kind: 'system', displayName: 'cron · weekly fire' },
        state: 'completed',
        started_at: '2026-05-27T09:00:00-07:00',
        ended_at: '2026-05-27T09:04:21-07:00',
        usage: { inputTokens: 8240, outputTokens: 1842, costUsd: 0.31 },
        turns: [
            {
                kind: 'user',
                id: 'h1-u',
                timestamp: '2026-05-27T09:00:00-07:00',
                text: 'Monday digest · cron firing',
            },
        ],
    }),
    makeHistorical({
        id: '01998a01-2222-7000-8000-0000000007d2',
        application: weeklyDigest,
        trigger: { kind: 'chat' },
        principal: { kind: 'human', userId: '1', displayName: 'Ben (test run)' },
        state: 'completed',
        started_at: '2026-05-27T17:11:00Z',
        ended_at: '2026-05-27T17:11:38Z',
        usage: { inputTokens: 1240, outputTokens: 318, costUsd: 0.041 },
        turns: [
            {
                kind: 'user',
                id: 'h2-u',
                timestamp: '2026-05-27T17:11:00Z',
                text: 'Test the new pr-callouts skill against last week.',
            },
        ],
    }),
    makeHistorical({
        id: '01998a01-2222-7000-8000-0000000007d3',
        application: weeklyDigest,
        trigger: { kind: 'chat' },
        principal: { kind: 'human', userId: '1', displayName: 'Ben' },
        state: 'failed',
        started_at: '2026-05-26T22:48:00Z',
        ended_at: '2026-05-26T22:48:12Z',
        usage: { inputTokens: 482, outputTokens: 12, costUsd: 0.004 },
        error: 'Tool `@posthog/query` returned 502 from ClickHouse twice in a row.',
        turns: [
            {
                kind: 'user',
                id: 'h3-u',
                timestamp: '2026-05-26T22:48:00Z',
                text: 'Quick dry-run of the digest.',
            },
        ],
    }),
    makeHistorical({
        id: '01998a01-2222-7000-8000-0000000007d4',
        application: weeklyDigest,
        trigger: { kind: 'cron', schedule: '0 9 * * MON', timezone: 'US/Pacific', firedAt: '2026-05-20T09:00:00-07:00' },
        principal: { kind: 'system', displayName: 'cron · weekly fire' },
        state: 'completed',
        started_at: '2026-05-20T09:00:00-07:00',
        ended_at: '2026-05-20T09:03:47-07:00',
        usage: { inputTokens: 7820, outputTokens: 1721, costUsd: 0.28 },
        turns: [
            {
                kind: 'user',
                id: 'h4-u',
                timestamp: '2026-05-20T09:00:00-07:00',
                text: 'Monday digest · cron firing',
            },
        ],
    }),
]

const releaseConciergeHistory: ChatSession[] = [
    releaseStreamingSession,
    releaseAwaitingSession,
    makeHistorical({
        id: '01998a01-2222-7000-8000-0000000007e1',
        application: releaseConcierge,
        trigger: { kind: 'cron', schedule: '0 16 * * THU', timezone: 'UTC', firedAt: '2026-05-21T15:46:00Z' },
        principal: { kind: 'system', displayName: 'cron · weekly cut' },
        state: 'completed',
        started_at: '2026-05-21T15:46:00Z',
        ended_at: '2026-05-21T16:02:18Z',
        usage: { inputTokens: 14200, outputTokens: 3420, costUsd: 0.62 },
        turns: [
            {
                kind: 'user',
                id: 'rh1-u',
                timestamp: '2026-05-21T15:46:00Z',
                text: 'Cut the v2.40 release.',
            },
        ],
    }),
    makeHistorical({
        id: '01998a01-2222-7000-8000-0000000007e2',
        application: releaseConcierge,
        trigger: {
            kind: 'slack',
            workspace: 'PostHog',
            channelId: 'C012XYZ',
            channelName: 'product-eng',
            threadTs: '1748120400.001050',
            rootMessage: '@release-concierge what shipped in v2.39?',
            invokedBy: 'Dylan',
        },
        principal: { kind: 'human', userId: '3', displayName: 'Dylan' },
        state: 'completed',
        started_at: '2026-05-24T10:20:00Z',
        ended_at: '2026-05-24T10:20:48Z',
        usage: { inputTokens: 2480, outputTokens: 620, costUsd: 0.082 },
        turns: [
            {
                kind: 'user',
                id: 'rh2-u',
                timestamp: '2026-05-24T10:20:00Z',
                text: '@release-concierge what shipped in v2.39?',
            },
            {
                kind: 'assistant',
                id: 'rh2-a',
                timestamp: '2026-05-24T10:20:08Z',
                parts: [
                    {
                        kind: 'text',
                        text:
                            'v2.39 (May 21):\n• ingest pipeline retry budget tuned (Dylan)\n• cohort calculation moved to async (Sam)\n• 6 quick fixes\n\nFull changelog: https://posthog.com/releases/v2-39',
                    },
                ],
            },
        ],
    }),
]

const incidentTriagerHistory: ChatSession[] = [
    triagerStreamingSession,
    makeHistorical({
        id: '01998a01-2222-7000-8000-0000000007f1',
        application: incidentTriager,
        principal: { kind: 'system', displayName: 'pagerduty · INC-4099' },
        state: 'completed',
        started_at: '2026-05-28T09:22:00Z',
        ended_at: '2026-05-28T09:24:08Z',
        usage: { inputTokens: 1420, outputTokens: 380, costUsd: 0.052 },
        turns: [
            {
                kind: 'user',
                id: 'ih1-u',
                timestamp: '2026-05-28T09:22:00Z',
                text: 'INC-4099: capture worker memory pressure in prod-us.',
            },
        ],
    }),
    makeHistorical({
        id: '01998a01-2222-7000-8000-0000000007f2',
        application: incidentTriager,
        principal: { kind: 'system', displayName: 'pagerduty · INC-4087' },
        state: 'aborted',
        started_at: '2026-05-27T03:14:00Z',
        ended_at: '2026-05-27T03:14:42Z',
        usage: { inputTokens: 320, outputTokens: 0, costUsd: 0.003 },
        turns: [
            {
                kind: 'user',
                id: 'ih2-u',
                timestamp: '2026-05-27T03:14:00Z',
                text: 'INC-4087: false positive, user aborted.',
            },
        ],
    }),
]

/** All sessions across the fleet, live + historical. */
const ALL_SESSIONS_BY_AGENT: Record<string, ChatSession[]> = {
    [weeklyDigest.id]: weeklyDigestHistory,
    [releaseConcierge.id]: releaseConciergeHistory,
    [incidentTriager.id]: incidentTriagerHistory,
}

/**
 * v0 fixture lookup; v0.1 swaps for a real REST call. Sorted newest-first
 * by start time.
 */
export function listSessionsForAgentFixture(applicationId: string): ChatSession[] {
    const list = ALL_SESSIONS_BY_AGENT[applicationId] ?? []
    return [...list].sort((a, b) => (timestampOf(b) ?? 0) - (timestampOf(a) ?? 0))
}

function timestampOf(s: ChatSession): number | undefined {
    if (s.started_at) {
        return new Date(s.started_at).getTime()
    }
    if (s.turns[0]) {
        return new Date(s.turns[0].timestamp).getTime()
    }
    return undefined
}

/** Per-agent rollup stats — used by the agent overview tab. */
export interface AgentStats {
    liveCount: number
    sessions24hCount: number
    spend24hUsd: number
    lastActivityAt?: string
    failureRate24h?: number
}

export function getAgentStatsFixture(applicationId: string): AgentStats {
    const sessions = listSessionsForAgentFixture(applicationId)
    const now = Date.now()
    const TWENTY_FOUR_H = 24 * 60 * 60 * 1000

    const recent = sessions.filter((s) => {
        const t = timestampOf(s)
        return t !== undefined && now - t < TWENTY_FOUR_H
    })

    const live = sessions.filter((s) =>
        ['streaming', 'awaiting_approval', 'awaiting_client_tool', 'idle', 'disconnected'].includes(s.state)
    )
    const spend = recent.reduce((acc, s) => acc + s.usage.costUsd, 0)
    const failures = recent.filter((s) => s.state === 'failed' || s.state === 'error' || s.state === 'aborted').length
    const failureRate = recent.length > 0 ? failures / recent.length : undefined

    return {
        liveCount: live.length,
        sessions24hCount: recent.length,
        spend24hUsd: spend,
        lastActivityAt: sessions[0]?.started_at,
        failureRate24h: failureRate,
    }
}

/**
 * Stub handlers for stories that want to demonstrate the client-fulfilled
 * tool surface without driving a real navigation. Logs to the console so
 * the action panel in Storybook shows what the agent invoked.
 */
export const focusHandler: ClientToolHandler<FocusArgs, FocusResult> = {
    id: '@posthog/ui/focus',
    handle: (args) => {
        // eslint-disable-next-line no-console
        console.info('[mock @posthog/ui/focus]', args)
        return { focused: true, kind: args.kind }
    },
}

export const toastHandler: ClientToolHandler<ToastArgs, ToastResult> = {
    id: '@posthog/ui/toast',
    handle: (args) => {
        // eslint-disable-next-line no-console
        console.info('[mock @posthog/ui/toast]', args)
        return { shown: true }
    },
}
