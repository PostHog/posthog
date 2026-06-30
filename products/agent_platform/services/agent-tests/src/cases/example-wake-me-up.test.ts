/**
 * Example bundle e2e — `services/agent-tests/src/examples/wake-me-up/`.
 *
 * Loads the wake-me-up bundle from disk, deploys it through the harness,
 * fires the cron trigger via `cronTick`, and drives the briefing-build
 * loop with the faux model. Like `example-sre-bot.test.ts`, this is a
 * wiring regression net — if the bundle's spec / skill paths drift out
 * of sync with the runner or tool registry, this case fails before the
 * bundle reaches production.
 *
 * Exercises cron + skills + both memory primitives (prose `memory-*`
 * for the full markdown, tabular `table-*` for the day-index row) so
 * a regression in any of those four surfaces lights up here first.
 */

import { readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { cronTick, newCronTickState } from '@posthog/agent-janitor'
import { serializeMemoryDoc } from '@posthog/agent-shared'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BUNDLE_ROOT = resolve(__dirname, '../examples/wake-me-up')
const BUNDLE_FILES = [
    'agent.md',
    'skills/briefing-template/SKILL.md',
    'skills/carry-over/SKILL.md',
    'skills/slack-post-format/SKILL.md',
] as const

async function loadBundle(): Promise<{ spec: Record<string, unknown>; files: Record<string, string> }> {
    const spec = JSON.parse(await readFile(join(BUNDLE_ROOT, 'spec.json'), 'utf-8')) as Record<string, unknown>
    const files: Record<string, string> = {}
    for (const path of BUNDLE_FILES) {
        files[path] = await readFile(join(BUNDLE_ROOT, path), 'utf-8')
    }
    return { spec, files }
}

/** Stub fetch — covers slack.com/api/* and any http-request URL. */
function stubFetch(responses: Record<string, unknown>): typeof fetch {
    return (async (input: string | URL | Request) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
        const match = Object.keys(responses).find((k) => url.includes(k))
        const body = match ? responses[match] : { ok: true }
        return {
            ok: true,
            status: 200,
            json: async () => body,
            text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
            headers: new Map([['content-type', 'application/json']]),
        } as unknown as Response
    }) as unknown as typeof fetch
}

describe('example: wake-me-up bundle', () => {
    let c: Cluster
    const originalFetch = global.fetch

    beforeEach(async () => {
        c = await buildCluster({
            // Slack tools resolve the bot token from the agent's encrypted_env
            // via `ctx.secret`; the tools throw if no token is wired even when
            // fetch is stubbed.
            resolveSecrets: async () => ({
                SLACK_BOT_TOKEN: 'xoxb-faux',
                SLACK_SIGNING_SECRET: 'signing-faux',
            }),
        })
    })

    afterEach(async () => {
        global.fetch = originalFetch
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('loads cleanly — spec parses, all 4 bundle files are present', async () => {
        const { spec, files } = await loadBundle()
        const skillPaths = (spec.skills as Array<{ path: string }>).map((s) => s.path)
        for (const p of skillPaths) {
            expect(files[p]).not.toBeUndefined()
        }
        expect(files['agent.md']).not.toBeUndefined()
        expect(files['agent.md'].length).toBeGreaterThan(500)
    })

    it('deploys end-to-end and runs through a full briefing build on the daily cron firing', async () => {
        const { spec, files } = await loadBundle()

        global.fetch = stubFetch({
            'slack.com/api/chat.postMessage': { ok: true, ts: '1700000050.000200', channel: 'C-personal' },
            'api.github.com': {
                total_count: 0,
                items: [],
            },
        })

        // First, populate yesterday's briefing row so carry-over discovery
        // has something to find. The agent doesn't write rows during
        // deployAgent; we seed directly through the harness's tabular
        // store handle. This proves the "yesterday → today" wiring across
        // separate runs without needing a multi-fire test.
        const teamId = 1
        // applicationId is assigned at deployAgent time, so we have to use
        // a recognizable scope. The cluster scopes by (teamId, applicationId);
        // here we'll seed AFTER deploy.

        // The faux model's script — a realistic full briefing build.
        c.setScript([
            // Phase 1: pin the output schema.
            fauxCallTool('@posthog/load-skill', { id: 'briefing-template' }),
            // Phase 2: load carry-over skill, then look for yesterday's row.
            fauxCallTool('@posthog/load-skill', { id: 'carry-over' }),
            fauxCallTool('@posthog/table-query', {
                table: 'briefings',
                order_by: 'date',
                desc: true,
                limit: 2,
            }),
            // Phase 3: read yesterday's markdown to extract `- [ ]` items.
            fauxCallTool('@posthog/memory-read', { path: 'briefings/2026-06-02.md' }),
            // Phase 4: gather PostHog signals.
            fauxCallTool('@posthog/query', { query: 'SELECT 1' }),
            // Phase 5: gather GitHub data (would be an external MCP in real
            // life; using http-request as the publicly-reachable v0 path).
            fauxCallTool('@posthog/http-request', {
                url: 'https://api.github.com/search/issues?q=is:open+is:pr+review-requested:@me',
            }),
            // Phase 6: write today's full markdown briefing.
            fauxCallTool('@posthog/memory-write', {
                path: 'briefings/2026-06-03.md',
                description: 'Morning briefing for 2026-06-03',
                content:
                    '# Start of day — 2026-06-03\n\n> Covers since 2026-06-02 17:00 PT\n\n## 🔍 Review requests\n\n_None today._\n\n## 🚀 Your work\n\n_None today._\n',
            }),
            // Phase 7: record the briefing-index row.
            fauxCallTool('@posthog/table-append', {
                table: 'briefings',
                rows: [
                    {
                        date: '2026-06-03',
                        path: 'briefings/2026-06-03.md',
                        item_count: 0,
                        posted_to_slack: true,
                    },
                ],
                dedupe_on: 'date',
            }),
            // Phase 8: project to mrkdwn, then post.
            fauxCallTool('@posthog/load-skill', { id: 'slack-post-format' }),
            fauxCallTool('@posthog/slack-post-message', {
                channel: 'C-personal',
                text: '*Start of day — 2026-06-03*\n\n_Quiet morning — nothing to action._',
            }),
            // Phase 9: end the turn.
            fauxText('Briefing posted, ending session.'),
        ])

        const { application, revision } = await c.deployAgent({ slug: 'wake-me-up', spec, files })

        // Seed yesterday's briefing index row + markdown so carry-over has
        // something to find. Same scope the runner uses at session start.
        const scope = { teamId, applicationId: application.id }
        await c.tabularStore.append(scope, 'briefings', [
            { date: '2026-06-02', path: 'briefings/2026-06-02.md', item_count: 2, posted_to_slack: true },
        ])
        await c.memoryStore.put(
            scope,
            'briefings/2026-06-02.md',
            serializeMemoryDoc({
                description: 'Morning briefing for 2026-06-02',
                tags: ['briefing'],
                content:
                    '# Start of day — 2026-06-02\n\n## 📋 Carry-over\n\n- [ ] Reply to gustavo thread\n- [ ] Triage #1234\n',
            })
        )

        // Fire the cron tick — this is what the janitor's setInterval does
        // in prod. We drive it directly so the test stays deterministic.
        // Window is (lastTickAt, now] (exclusive at start), so t0 must land
        // strictly BEFORE the 08:00 PT firing for t1 to catch it.
        const state = newCronTickState()
        const deps = { revisions: c.revisions, queue: c.queue, encryption: c.encryption }
        // 2026-06-03 is a Wednesday; 08:00 PT (PDT, UTC-7) = 15:00 UTC.
        const t0 = new Date('2026-06-03T14:59:00Z') // 07:59 PT — seeds
        await cronTick({ ...deps, now: () => t0 }, state)
        // t1 advances past 08:00 PT; window (14:59, 15:01] catches 15:00.
        const t1 = new Date('2026-06-03T15:01:00Z')
        const r1 = await cronTick({ ...deps, now: () => t1 }, state)
        expect(r1.fired).toBe(1)
        expect(r1.errors).toBe(0)

        await c.drain({ iterations: 100 })

        // Find the firing-triggered session via its idempotency key shape.
        const minute = Math.floor(new Date('2026-06-03T15:00:00Z').getTime() / 60_000)
        const session = await c.queue.findByIdempotencyKey(
            application.id,
            `cron:${revision.id}:morning-brief:${minute}`
        )
        expect(session).not.toBeNull()
        expect(session!.state).toBe('completed')
        expect(session!.trigger_metadata).toMatchObject({
            kind: 'cron',
            cron_name: 'morning-brief',
        })

        // The seed message is the placeholder-expanded prompt; the bundle's
        // cron config uses {fired_at:date} so the date should appear there.
        const seed = session!.conversation[0] as { role: string; content: string }
        expect(seed.role).toBe('user')
        expect(seed.content).toContain('2026-06-03')

        const calledTools = session!.conversation
            .filter((m) => m.role === 'toolResult')
            .map((m) => (m as { toolName?: string }).toolName)
        expect(calledTools).toEqual([
            '@posthog/load-skill',
            '@posthog/load-skill',
            '@posthog/table-query',
            '@posthog/memory-read',
            '@posthog/query',
            '@posthog/http-request',
            '@posthog/memory-write',
            '@posthog/table-append',
            '@posthog/load-skill',
            '@posthog/slack-post-message',
        ])

        // Confirm today's briefing row + markdown landed — proves the full
        // memory-write + table-append round-trip through real S3.
        const rows = await c.tabularStore.query(scope, 'briefings', { where: { date: '2026-06-03' } })
        expect(rows).toHaveLength(1)
        expect(rows[0]).toMatchObject({
            date: '2026-06-03',
            path: 'briefings/2026-06-03.md',
            posted_to_slack: true,
        })

        const file = await c.memoryStore.read(scope, 'briefings/2026-06-03.md')
        expect(file).not.toBeNull()
        expect(file!.content).toContain('Start of day — 2026-06-03')
    })
})
