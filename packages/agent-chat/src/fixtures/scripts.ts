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
import { weeklyDigest } from './agents'

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

export const conciergeAgentMakeChange: Script = {
    id: 'concierge.agent.make-change',
    match: matchesAny('make a change', 'change something', 'help me plan'),
    steps: [
        { kind: 'text', text: 'Sure. Let me show you the current bundle so we can decide what to touch.', chunkMs: 12 },
        { kind: 'pause', ms: 250 },
        {
            kind: 'tool_call',
            toolId: '@posthog/ui/focus',
            fulfillment: 'client',
            args: { kind: 'file', path: 'skills/digest-shape.md' },
            pendingMs: 250,
        },
        {
            kind: 'text',
            text: '\n\nThe `digest-shape` skill is the format spec — most "make the digest read better" changes start here. The `pr-callouts` skill (added in the draft) covers GitHub.\n\nWhat\'s the change you want?',
            chunkMs: 12,
        },
    ],
}

/**
 * Demos the focus-with-mutation flow: the concierge edits agent.md, then
 * focuses the user on it. The tool call declares `mutations[]`, so the
 * console's mock-api overlay receives the new content + bumps the
 * entity revision. With focus mode on, the file row + viewer flair as
 * the new content lands. With focus mode off, the data still updates
 * but the UI stays calm.
 */
const tightenAgentMdMutationId = 'mut-tighten-agent-md-001'
const tightenedAgentMdContent = `# Weekly digest

You write the Monday-morning summary that lands in #product-eng. The
audience is engineers + PMs who weren't paying close attention last
week — your job is to surface the 3-5 things they'd care most about
without making them dig.

## Sources to pull from

Use \`@posthog/query\` to fetch:

- Top events by volume (last 7 days)
- Notable changes vs. the previous 7-day window
- Any feature flag rollouts that hit 100%
- **Friday's deploys** — pull the deploy log for Fri/Sat to flag
  what shipped right before the weekend (highest blast-radius risk)

## Voice

Casual but tight. No emoji, no headlines that say "Exciting news!".
Lead with the numbers; let the prose stay out of the way.

## What good looks like

A typical digest is 6-10 bullets, total length under 1500 chars.
Each bullet is one fact + one quick interpretation.

When you load the digest-shape skill via \`@posthog/load-skill\` you'll
see the exact format the team has converged on.
`

export const conciergeAgentTightenPrompt: Script = {
    id: 'concierge.agent.tighten-prompt',
    match: matchesAny('mention friday', 'friday deploy', 'tighten the prompt', 'add friday'),
    steps: [
        { kind: 'thinking', text: 'Pulling agent.md, adding a Friday-deploys callout to the sources list…' },
        { kind: 'pause', ms: 300 },
        {
            kind: 'tool_call',
            toolId: 'posthog_update_bundle_file',
            fulfillment: 'server',
            args: {
                application_id: weeklyDigest.id,
                path: 'agent.md',
                summary: 'Add Friday deploys to the sources list',
            },
            result: {
                ok: true,
                body: {
                    revision_id: '01998a01-1111-7000-8000-000000000a03',
                    sha256: 'sha256:friday-deploys-call-out',
                    mutation_id: tightenAgentMdMutationId,
                },
            },
            pendingMs: 600,
            mutations: [
                {
                    entityKey: `bundle-file:${weeklyDigest.id}:agent.md`,
                    mutationId: tightenAgentMdMutationId,
                    payload: { newContent: tightenedAgentMdContent },
                },
            ],
        },
        {
            kind: 'text',
            text: 'Patched `agent.md` — added a bullet under "Sources to pull from" calling out Friday/Saturday deploys.',
            chunkMs: 14,
        },
        {
            kind: 'tool_call',
            toolId: '@posthog/ui/focus',
            fulfillment: 'client',
            args: { kind: 'file', path: 'agent.md', mutationId: tightenAgentMdMutationId },
            pendingMs: 200,
        },
        {
            kind: 'text',
            text: "\n\nOpening it now — the new bullet should flair as the bundle re-reads.",
            chunkMs: 14,
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
    conciergeAgentTightenPrompt,
    conciergeAgentExplain,
    conciergeAgentMakeChange,
    conciergeAgentRecentSessions,
    conciergeListWhatChanged,
]

export const playgroundScripts: Script[] = [playgroundDryRun]
