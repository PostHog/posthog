/**
 * Bundle file fixtures — what the on-disk shape of an agent bundle looks
 * like once the runner unpacks it.
 *
 * Flat list of files keyed by path; the BundleTree component derives the
 * folder hierarchy from the path slashes. Mirrors the real bundle
 * layout from `agent-authoring-flow.md` §6:
 *
 *   agent.md                       — system prompt
 *   skills/<id>.md                 — one skill per file
 *   tools/<id>/source.ts           — custom tool TS
 *   tools/<id>/schema.json         — args shape + required secrets
 *   tests/<name>.json              — test specs
 */

export type BundleFileLanguage = 'markdown' | 'typescript' | 'json' | 'text'

export interface BundleFile {
    path: string
    language: BundleFileLanguage
    content: string
}

export const weeklyDigestBundle: BundleFile[] = [
    {
        path: 'agent.md',
        language: 'markdown',
        content: `# Weekly digest

You write the Monday-morning summary that lands in #product-eng. The
audience is engineers + PMs who weren't paying close attention last
week — your job is to surface the 3-5 things they'd care most about
without making them dig.

## Sources to pull from

Use \`@posthog/query\` to fetch:

- Top events by volume (last 7 days)
- Notable changes vs. the previous 7-day window
- Any feature flag rollouts that hit 100%

## Voice

Casual but tight. No emoji, no headlines that say "Exciting news!".
Lead with the numbers; let the prose stay out of the way.

## What good looks like

A typical digest is 6-10 bullets, total length under 1500 chars.
Each bullet is one fact + one quick interpretation.

When you load the digest-shape skill via \`@posthog/load-skill\` you'll
see the exact format the team has converged on.
`,
    },
    {
        path: 'skills/digest-shape.md',
        language: 'markdown',
        content: `# digest-shape

The Monday digest converges on this format:

\`\`\`
**Last week in product-eng**

- <metric> went <up/down> <%> WoW — <one-sentence interpretation>
- <event name> launched / rolled out / shipped
- <thing the team should know but might have missed>

— posted by @weekly-digest
\`\`\`

Rules:
- Three to five bullets, never more.
- No bullet uses more than one number.
- If a number's "interpretation" is "we don't know", say so — don't
  invent a reason.
- Sign-off line is mandatory; it's how reply-pings get routed.
`,
    },
    {
        path: 'skills/pr-callouts.md',
        language: 'markdown',
        content: `# pr-callouts

When you have GitHub access (via \`@posthog/github-search\`), surface
PRs that are notable. A PR is notable if any of these are true:

- It touched > 500 lines AND was reviewed by < 2 people
- The title contains "fix" + "regression" or "rollback"
- It introduced a new dependency
- It deleted a deployment script

Format inline with the digest, not as a separate section. Example:

> #16842 (auth refactor) merged with one reviewer — flagging for awareness.

Do not list every merged PR.
`,
    },
    {
        path: 'tools/in-app-helper/source.ts',
        language: 'typescript',
        content: `/**
 * Generates a Slack-friendly summary block from a digest body.
 *
 * Splits long-form prose into Slack's section blocks so the formatting
 * renders correctly on mobile clients (where long markdown collapses
 * into a wall of text otherwise).
 */

import type { ToolDefinition } from '@posthog/agent-tools'

export const formatDigestForSlack: ToolDefinition = {
    id: 'format-digest-for-slack',
    description: 'Splits a long digest body into Slack section blocks.',
    args: {
        body: { type: 'string', description: 'The full digest text' },
    },
    async run({ args }) {
        const blocks = splitIntoBlocks(args.body)
        return { ok: true, body: { blocks } }
    },
}

function splitIntoBlocks(body: string): Array<{ type: 'section'; text: { type: 'mrkdwn'; text: string } }> {
    return body
        .split(/\\n\\n+/)
        .filter((p) => p.trim().length > 0)
        .map((p) => ({ type: 'section', text: { type: 'mrkdwn', text: p } }))
}
`,
    },
    {
        path: 'tools/in-app-helper/schema.json',
        language: 'json',
        content: JSON.stringify(
            {
                description: 'Splits a long digest body into Slack section blocks.',
                args: {
                    body: { type: 'string', description: 'The full digest text' },
                },
                secrets: [],
            },
            null,
            2
        ),
    },
    {
        path: 'tests/happy-path.json',
        language: 'json',
        content: JSON.stringify(
            {
                name: 'happy path — Monday firing',
                trigger: {
                    type: 'cron',
                    fired_at: '2026-05-25T09:00:00-07:00',
                },
                expected: {
                    tool_calls_include: ['@posthog/query', '@posthog/slack-post-message'],
                    assistant_text_matches: '^\\\\*\\\\*Last week in product-eng\\\\*\\\\*',
                    max_turns: 8,
                    must_complete_within_ms: 60000,
                },
            },
            null,
            2
        ),
    },
]
