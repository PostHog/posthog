/**
 * Demo scripts for the FakeRunnerController.
 *
 * Each script answers a specific user message with a sequence of
 * streaming text, thinking, and tool calls — including
 * `@posthog/ui/focus` calls that the console's handler turns into
 * real page navigation.
 *
 * These are intentionally hand-written and tailored to the starter
 * prompts in `context.ts` so the dock has something compelling to
 * play when a user clicks a chip.
 *
 * v0.2+ replaces this entire file with real session transport
 * against the runner.
 */

import type { Script } from '../fake-runner'

const matchesAny = (...needles: string[]) => (text: string): boolean =>
    needles.some((n) => text.toLowerCase().includes(n.toLowerCase()))

/* ── Agent-list context ──────────────────────────────────────────── */

export const conciergeListWhatChanged: Script = {
    id: 'concierge.list.what-changed',
    match: matchesAny('what changed', 'changed across', 'this week'),
    steps: [
        { kind: 'thinking', text: 'Pulling promote events + spec diffs across all 4 agents…' },
        { kind: 'pause', ms: 250 },
        {
            kind: 'tool_call',
            toolId: 'agent-applications-revisions-list',
            fulfillment: 'server',
            args: { team_id: 2, since: '7d' },
            result: {
                ok: true,
                body: [
                    { application: 'weekly-digest', promoted: 1, drafts: 1 },
                    { application: 'release-concierge', promoted: 0, drafts: 0 },
                    { application: 'incident-triager', promoted: 2, drafts: 0 },
                ],
            },
            pendingMs: 600,
        },
        {
            kind: 'text',
            text: 'Quick rundown — three things stand out:\n\n• weekly-digest has a new draft adding `@posthog/github-search` for PR callouts\n• incident-triager shipped two revisions this week (4099 + 4112 follow-ups)\n• release-concierge has been quiet — likely because we cut v2.40 cleanly\n\nWant me to open weekly-digest so you can review the draft?',
            chunkMs: 14,
        },
    ],
}

/* ── Agent (weekly-digest) context ──────────────────────────────── */

export const conciergeAgentExplain: Script = {
    id: 'concierge.agent.explain',
    match: matchesAny('explain', 'rundown', 'walk me through what'),
    steps: [
        { kind: 'thinking', text: 'Loading the live revision spec + agent.md to summarize…' },
        { kind: 'pause', ms: 200 },
        {
            kind: 'tool_call',
            toolId: '@posthog/ui/focus',
            fulfillment: 'client',
            args: { kind: 'file', path: 'agent.md' },
            pendingMs: 200,
        },
        { kind: 'pause', ms: 200 },
        {
            kind: 'text',
            text: 'Showing you `agent.md`. The shape:\n\n• Fires every Monday 9am Pacific via cron\n• Pulls top events + WoW deltas using `@posthog/query`\n• Posts a 6-10 bullet summary to #product-eng via Slack\n• Loads the `digest-shape` skill for the format the team has converged on\n\nThe draft (019…a02) adds `@posthog/github-search` and a `pr-callouts` skill for surfacing notable PRs inline.',
            chunkMs: 12,
        },
    ],
}

export const conciergeAgentShowConfig: Script = {
    id: 'concierge.agent.show-config',
    match: matchesAny('show me the config', 'how is it configured', 'configuration'),
    steps: [
        { kind: 'text', text: 'Opening the configuration tab.', chunkMs: 12 },
        { kind: 'pause', ms: 150 },
        {
            kind: 'tool_call',
            toolId: '@posthog/ui/focus',
            fulfillment: 'client',
            args: { kind: 'spec_section', section: 'triggers' },
            pendingMs: 150,
        },
    ],
}

export const conciergeAgentRecentSessions: Script = {
    id: 'concierge.agent.recent-sessions',
    match: matchesAny('recent sessions', 'recent activity', "anything unusual"),
    steps: [
        { kind: 'thinking', text: 'Checking the last 7 days of sessions…' },
        { kind: 'pause', ms: 200 },
        {
            kind: 'tool_call',
            toolId: '@posthog/ui/focus',
            fulfillment: 'client',
            args: { kind: 'tab', tab: 'sessions' },
            pendingMs: 200,
        },
        {
            kind: 'text',
            text: 'One thing worth a look — the manual dry-run on May 26 failed with a ClickHouse 502 on `@posthog/query`. The cron fires the same morning succeeded, so it looks transient, but worth keeping an eye on.',
            chunkMs: 14,
        },
    ],
}

/* ── Playground context ──────────────────────────────────────────── */

export const playgroundDryRun: Script = {
    id: 'playground.dry-run',
    match: matchesAny('run for last week', 'pretend it', "monday morning", 'real example'),
    steps: [
        {
            kind: 'tool_call',
            toolId: '@posthog/query',
            fulfillment: 'server',
            args: {
                hogql: "select event, count() from events where timestamp > now() - interval 7 day group by event order by 2 desc limit 5",
            },
            result: {
                ok: true,
                body: [
                    ['$pageview', 18420],
                    ['$autocapture', 9112],
                    ['agent_session_started', 312],
                    ['feature_flag_called', 1450],
                    ['$identify', 904],
                ],
            },
            pendingMs: 700,
        },
        {
            kind: 'text',
            text: '**Last week in product-eng**\n\n• $pageview held at 18.4k (flat WoW — onboarding traffic still steady)\n• agent_session_started up to 312, mostly weekly-digest + release-concierge runs\n• feature_flag_called bumped to 1.45k — there were two new flag rollouts mid-week\n\n— posted by @weekly-digest',
            chunkMs: 14,
        },
        { kind: 'pause', ms: 200 },
        {
            kind: 'text',
            text: '\n\n(That\'s what would land in #product-eng. Want me to dry-run it to a personal DM instead, or change the format?)',
            chunkMs: 14,
        },
    ],
}

/* ── Fallback ────────────────────────────────────────────────────── */

export const fallbackScript: Script = {
    id: 'fallback',
    match: () => true,
    steps: [
        { kind: 'thinking', text: 'No script matched — real concierge handling lands in v0.2.' },
        { kind: 'pause', ms: 200 },
        {
            kind: 'text',
            text: "Got it. In the real build I'd take the next step — for the v0 mock I only have a handful of scripted responses wired up. Try one of the suggested prompts at the top of the dock?",
            chunkMs: 14,
        },
    ],
}

/* ── Aggregates ──────────────────────────────────────────────────── */

/**
 * Scripts the dock plays in **concierge** mode. Order matters — the
 * first matching script wins, so put narrower matchers first.
 */
export const conciergeScripts: Script[] = [
    conciergeAgentShowConfig,
    conciergeAgentExplain,
    conciergeAgentRecentSessions,
    conciergeListWhatChanged,
]

export const playgroundScripts: Script[] = [playgroundDryRun]
