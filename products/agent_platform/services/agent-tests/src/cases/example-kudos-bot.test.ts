/**
 * Example bundle e2e — `services/agent-tests/src/examples/kudos-bot/`.
 *
 * Loads the kudos-bot bundle from disk, deploys it through the harness,
 * and drives both halves of the agent with the faux model:
 *
 *   1. Capture — a signed Slack `app_mention` ("kudos to @jane …") runs
 *      through react → append row → write profile, proving the slack
 *      trigger + native slack tools + tabular + prose memory all wire up.
 *   2. Celebrate — the weekly `cron` firing (`cronTick`) queries last
 *      week's rows and posts the digest.
 *
 * Like the sibling example tests this is a WIRING regression net, not a
 * real-inference test — the model is faux; the assertions are about the
 * bundle's spec / skill paths / tool ids staying in sync with the runner
 * and tool registry, not about whether the agent's prose is good.
 */

import { readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { cronTick, newCronTickState } from '@posthog/agent-janitor'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

const SLACK_SECRET = 'kudos-test-slack-secret'
const WORKSPACE = 'T0XXXXXXX' // matches the bundle's trusted_workspaces placeholder

const __dirname = dirname(fileURLToPath(import.meta.url))
const BUNDLE_ROOT = resolve(__dirname, '../examples/kudos-bot')
const BUNDLE_FILES = [
    'agent.md',
    'skills/capturing-kudos/SKILL.md',
    'skills/kudos-storage/SKILL.md',
    'skills/weekly-summary/SKILL.md',
] as const

async function loadBundle(): Promise<{ spec: Record<string, unknown>; files: Record<string, string> }> {
    const spec = JSON.parse(await readFile(join(BUNDLE_ROOT, 'spec.json'), 'utf-8')) as Record<string, unknown>
    const files: Record<string, string> = {}
    for (const path of BUNDLE_FILES) {
        files[path] = await readFile(join(BUNDLE_ROOT, path), 'utf-8')
    }
    return { spec, files }
}

/** A Slack `app_mention` callback carrying the workspace id so the
 *  trusted_workspaces gate (set to `[WORKSPACE]` in the bundle) passes. */
function kudosMention(): Record<string, unknown> {
    return {
        type: 'event_callback',
        event_id: 'Ev_kudos_capture',
        event: {
            type: 'app_mention',
            team: WORKSPACE,
            channel: 'C-kudos',
            user: 'U-ben',
            text: '<@U-bot> kudos to <@U-jane> for unblocking the events migration — saved us a day',
            ts: '1717430400.000100',
        },
    }
}

/** A Slack event in a single channel/thread, carrying the workspace id so the
 *  trusted_workspaces gate passes. The opener is an `app_mention`; follow-ups
 *  are plain `message` events that `auto_resume_threads` routes back into the
 *  open session. All from the same user (U-ben) so the per-session ACL admits
 *  them without an elevation round-trip. */
function slackThreadEvent(opts: {
    eventType: 'app_mention' | 'message'
    text: string
    ts: string
    thread_ts?: string
    event_id: string
}): Record<string, unknown> {
    return {
        type: 'event_callback',
        event_id: opts.event_id,
        event: {
            type: opts.eventType,
            team: WORKSPACE,
            channel: 'C-kudos',
            user: 'U-ben',
            text: opts.text,
            ts: opts.ts,
            thread_ts: opts.thread_ts,
        },
    }
}

/** One captured Slack Web API call. */
interface SlackCall {
    method: string // slack api method, e.g. chat.postMessage
    auth?: string
    body: Record<string, unknown>
}

/** Slack tools send form-encoded bodies; the reply relay sends JSON. Parse
 *  either into a plain object so assertions can read the fields. */
function parseSlackBody(body: RequestInit['body']): Record<string, unknown> {
    if (typeof body !== 'string') {
        return {}
    }
    if (body.trimStart().startsWith('{')) {
        try {
            return JSON.parse(body) as Record<string, unknown>
        } catch {
            return {}
        }
    }
    return Object.fromEntries(new URLSearchParams(body))
}

/** A recording `HttpClient` stand-in. The native `@posthog/slack-*` tools
 *  dispatch through `ctx.http.fetch` (NOT `global.fetch`), so the reliable
 *  way to intercept + assert on the Slack calls is to pass this as the
 *  cluster's `http` — same approach as `example-sre-bot.test.ts`. */
function buildSlackRecorder(): { http: { fetch: typeof fetch }; calls: SlackCall[] } {
    const calls: SlackCall[] = []
    const http = {
        fetch: ((input: string | URL, init?: RequestInit) => {
            const url = typeof input === 'string' ? input : input.toString()
            if (url.includes('slack.com/api/')) {
                const headers = (init?.headers ?? {}) as Record<string, string>
                calls.push({
                    method: url.replace('https://slack.com/api/', ''),
                    auth: headers.Authorization,
                    body: parseSlackBody(init?.body),
                })
            }
            return Promise.resolve({
                ok: true,
                status: 200,
                json: async () => ({ ok: true, ts: '1717862400.000100', channel: 'C-kudos' }),
                text: async () => '{"ok":true}',
                headers: new Map([['content-type', 'application/json']]),
            } as unknown as Response)
        }) as unknown as typeof fetch,
    }
    return { http, calls }
}

/** Build a cluster wired with the Slack secrets + an http recorder. The
 *  native slack tools resolve SLACK_BOT_TOKEN via ctx.secret; the slack
 *  TRIGGER verifies the signature with SLACK_SIGNING_SECRET out of
 *  encrypted_env (wired per-agent on deployAgent). */
async function buildKudosCluster(http: { fetch: typeof fetch }): Promise<Cluster> {
    return buildCluster({
        resolveSecrets: async () => ({
            SLACK_BOT_TOKEN: 'xoxb-faux',
            SLACK_SIGNING_SECRET: SLACK_SECRET,
        }),
        http,
    })
}

describe('example: kudos-bot bundle', () => {
    let c: Cluster
    let slackCalls: SlackCall[]

    beforeEach(async () => {
        const recorder = buildSlackRecorder()
        slackCalls = recorder.calls
        c = await buildKudosCluster(recorder.http)
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('loads cleanly — spec parses, every skill path resolves to a bundle file', async () => {
        const { spec, files } = await loadBundle()
        const skillPaths = (spec.skills as Array<{ path: string }>).map((s) => s.path)
        for (const p of skillPaths) {
            expect(files[p]).not.toBeUndefined()
        }
        expect(files['agent.md']).not.toBeUndefined()
        expect(files['agent.md'].length).toBeGreaterThan(500)
    })

    it('captures a kudos from a Slack @mention — reacts, records the row, writes the profile', async () => {
        const { spec, files } = await loadBundle()

        c.setScript([
            // Phase 1: how to read a kudos.
            fauxCallTool('@posthog/load-skill', { id: 'capturing-kudos' }),
            // Phase 2: the storage schema + dedupe key.
            fauxCallTool('@posthog/load-skill', { id: 'kudos-storage' }),
            // Phase 3: is there already a profile for this recipient?
            fauxCallTool('@posthog/memory-search', { cue: 'jane', prefix: 'people/' }),
            // Phase 4: record the kudos row, deduped on kudos_id.
            fauxCallTool('@posthog/table-append', {
                table: 'kudos',
                rows: [
                    {
                        kudos_id: 'slack:C-kudos:1717430400.000100:<@U-jane>',
                        recipient_handle: '<@U-jane>',
                        giver_handle: '<@U-ben>',
                        message: 'unblocking the events migration — saved us a day',
                        themes: 'teamwork,above-and-beyond',
                        given_at: '2026-06-03T16:00:00Z',
                        week: '2026-W23',
                        source: 'slack',
                        permalink: '',
                    },
                ],
                dedupe_on: 'kudos_id',
            }),
            // Phase 5: first kudos for this person → create their profile.
            fauxCallTool('@posthog/memory-write', {
                path: 'people/u-jane.md',
                description: 'Kudos profile for <@U-jane>',
                content:
                    '# <@U-jane>\n\n## Highlights\n\n- 2026-06-03 — unblocked the events migration, saved the team a day (from <@U-ben>) · _teamwork, above-and-beyond_\n',
                tags: ['person', 'kudos'],
            }),
            // Phase 6: confirm with a :tada: reaction on the original message.
            fauxCallTool('@posthog/slack-react', {
                channel: 'C-kudos',
                ts: '1717430400.000100',
                name: 'tada',
            }),
            // Phase 7: leave the thread open for follow-ups.
            fauxText('Recorded — kudos to <@U-jane> for the migration unblock. 🎉'),
        ])

        const { application } = await c.deployAgent({
            slug: 'kudos-bot',
            spec,
            files,
            encrypted_env: { SLACK_SIGNING_SECRET: SLACK_SECRET },
        })

        const res = await c.slackPost('kudos-bot', 'events', kudosMention(), SLACK_SECRET)
        expect(res.status).toBe(200)
        expect(res.body.session_id).toBeTruthy()
        await c.drain({ iterations: 100 })

        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')

        // The seed message carries the [slack] envelope so the model can route
        // its reply/react back to the right channel + message.
        const seed = session!.conversation.find((m) => m.role === 'user') as { role: string; content: string }
        expect(seed.content).toContain('[slack]')
        expect(seed.content).toContain('channel: C-kudos')
        expect(seed.content).toContain('kudos to <@U-jane>')

        const calledTools = session!.conversation
            .filter((m) => m.role === 'toolResult')
            .map((m) => (m as { toolName?: string }).toolName)
        expect(calledTools).toEqual([
            '@posthog/load-skill', // capturing-kudos
            '@posthog/load-skill', // kudos-storage
            '@posthog/memory-search',
            '@posthog/table-append',
            '@posthog/memory-write',
            '@posthog/slack-react',
        ])

        // The kudos row landed in the tabular store — proves the tool wired
        // through to a real S3 backend, scoped to this app.
        const scope = { teamId: session!.team_id, applicationId: application.id }
        const rows = await c.tabularStore.query(scope, 'kudos', { where: { recipient_handle: '<@U-jane>' } })
        expect(rows).toHaveLength(1)
        expect(rows[0]).toMatchObject({
            recipient_handle: '<@U-jane>',
            giver_handle: '<@U-ben>',
            week: '2026-W23',
            source: 'slack',
        })

        // The recipient profile landed in prose memory (un-gated write).
        const profile = await c.memoryStore.read(scope, 'people/u-jane.md')
        expect(profile.content).toContain('unblocked the events migration')
        expect(profile.frontmatter.tags).toContain('kudos')

        // The :tada: confirm reaction actually hit the Slack Web API with the
        // resolved bot token (substitution fired, no leftover placeholder).
        const react = slackCalls.find((s) => s.method === 'reactions.add')
        expect(react).not.toBeUndefined()
        expect(react!.auth).toBe('Bearer xoxb-faux')
        expect(react!.body).toMatchObject({ channel: 'C-kudos', name: 'tada' })
    })

    it('asks one clarifying question when the recipient is missing, then records on the in-thread reply', async () => {
        const { spec, files } = await loadBundle()

        // Single script queue, consumed one entry per model call across BOTH
        // turns (the faux provider walks it sequentially). Turn 1 ends on a
        // natural-stop text → the session goes `completed` (open) and waits;
        // the in-thread reply resumes it and the runner walks the rest.
        c.setScript([
            // --- Turn 1: opener has no recipient → ask, don't record. ---
            fauxCallTool('@posthog/load-skill', { id: 'capturing-kudos' }),
            fauxCallTool('@posthog/slack-post-message', {
                channel: 'C-kudos',
                thread_ts: '2000.000100',
                text: '🙌 love it — who is this kudos for?',
            }),
            fauxText('Asked who the kudos is for; waiting for the reply in-thread.'),
            // --- Turn 2: the reply names the recipient → record it. ---
            fauxCallTool('@posthog/slack-read-thread', { channel: 'C-kudos', thread_ts: '2000.000100' }),
            fauxCallTool('@posthog/load-skill', { id: 'kudos-storage' }),
            fauxCallTool('@posthog/table-append', {
                table: 'kudos',
                rows: [
                    {
                        kudos_id: 'slack:C-kudos:2000.000100:<@U-jane>',
                        recipient_handle: '<@U-jane>',
                        giver_handle: '<@U-ben>',
                        message: 'shipping the on-call dashboard',
                        themes: 'shipping',
                        given_at: '2026-06-03T17:00:00Z',
                        week: '2026-W23',
                        source: 'slack',
                        permalink: '',
                    },
                ],
                dedupe_on: 'kudos_id',
            }),
            fauxCallTool('@posthog/memory-write', {
                path: 'people/u-jane.md',
                description: 'Kudos profile for <@U-jane>',
                content:
                    '# <@U-jane>\n\n## Highlights\n\n- 2026-06-03 — shipped the on-call dashboard (from <@U-ben>) · _shipping_\n',
                tags: ['person', 'kudos'],
            }),
            fauxCallTool('@posthog/slack-react', { channel: 'C-kudos', ts: '2000.000100', name: 'tada' }),
            fauxText('Recorded — kudos to <@U-jane> for the on-call dashboard. 🎉'),
        ])

        const { application } = await c.deployAgent({
            slug: 'kudos-bot',
            spec,
            files,
            encrypted_env: { SLACK_SIGNING_SECRET: SLACK_SECRET },
        })
        const scope = { teamId: 1, applicationId: application.id }

        // --- Turn 1: opener @mention with no recipient. ---
        const opener = await c.slackPost(
            'kudos-bot',
            'events',
            slackThreadEvent({
                eventType: 'app_mention',
                text: '<@U-bot> big kudos for shipping the on-call dashboard today!',
                ts: '2000.000100',
                event_id: 'Ev_clarify_open',
            }),
            SLACK_SECRET
        )
        expect(opener.status).toBe(200)
        expect(opener.body.resumed).toBe(false)
        const sessionId = opener.body.session_id as string
        await c.drain({ iterations: 100 })

        // The bot asked instead of recording: a clarifying post went out, and
        // NO kudos row exists yet. This is the behaviour that distinguishes the
        // bot from a dumb form — it picks up the missing recipient.
        const afterAsk = await c.queue.get(sessionId)
        expect(afterAsk!.state).toBe('completed')
        // Skip the runner's transient "Working on it…" status post — we want
        // the agent's actual clarifying reply.
        const question = slackCalls.find(
            (s) => s.method === 'chat.postMessage' && !String(s.body.text ?? '').includes('Working on it')
        )
        expect(question).not.toBeUndefined()
        expect(question!.body).toMatchObject({ channel: 'C-kudos', thread_ts: '2000.000100' })
        expect(String(question!.body.text)).toContain('who is this kudos for')
        expect(await c.tabularStore.count(scope, 'kudos')).toBe(0)

        // --- Turn 2: the user replies in-thread with the recipient. The reply
        // is a plain `message` event (no @mention); auto_resume_threads routes
        // it back into the open session. ---
        const reply = await c.slackPost(
            'kudos-bot',
            'events',
            slackThreadEvent({
                eventType: 'message',
                text: "oh — it's for <@U-jane>!",
                ts: '2000.000300',
                thread_ts: '2000.000100',
                event_id: 'Ev_clarify_reply',
            }),
            SLACK_SECRET
        )
        expect(reply.status).toBe(200)
        expect(reply.body.resumed).toBe(true)
        expect(reply.body.session_id).toBe(sessionId)
        await c.drain({ iterations: 100 })

        // Same session advanced; both user messages landed in the one thread.
        const session = await c.queue.get(sessionId)
        expect(session!.state).toBe('completed')
        const userMsgs = session!.conversation.filter((m) => m.role === 'user')
        expect(userMsgs.length).toBe(2)

        // The full tool order across both turns: ask → (reply) → read thread →
        // record → confirm.
        const calledTools = session!.conversation
            .filter((m) => m.role === 'toolResult')
            .map((m) => (m as { toolName?: string }).toolName)
        expect(calledTools).toEqual([
            '@posthog/load-skill', // capturing-kudos (turn 1)
            '@posthog/slack-post-message', // the clarifying question
            '@posthog/slack-read-thread', // turn 2: re-read the thread
            '@posthog/load-skill', // kudos-storage
            '@posthog/table-append',
            '@posthog/memory-write',
            '@posthog/slack-react',
        ])

        // The kudos the user clarified now exists — recorded only after the
        // missing recipient arrived.
        const rows = await c.tabularStore.query(scope, 'kudos', { where: { recipient_handle: '<@U-jane>' } })
        expect(rows).toHaveLength(1)
        expect(rows[0]).toMatchObject({
            recipient_handle: '<@U-jane>',
            message: 'shipping the on-call dashboard',
            week: '2026-W23',
        })
    })

    it('posts the weekly digest on the Monday cron firing, grouping last week’s kudos', async () => {
        const { spec, files } = await loadBundle()

        c.setScript([
            // Phase 1: the digest format + which-week logic.
            fauxCallTool('@posthog/load-skill', { id: 'weekly-summary' }),
            // Phase 2: pull last week's kudos (the ISO week before the firing week).
            fauxCallTool('@posthog/table-query', {
                table: 'kudos',
                where: { week: '2026-W23' },
                order_by: 'recipient_handle',
            }),
            // Phase 3: post the celebratory digest to the kudos channel.
            fauxCallTool('@posthog/slack-post-message', {
                channel: 'C-kudos',
                text: ':tada: *Kudos — week of Jun 1–7* :tada:\n\n*<@U-jane>* — 2 kudos\n*<@U-raj>* — 1 kudos\n\n─────\n3 kudos this week. Keep ’em coming — @mention me.',
            }),
            // Phase 4: end the session; next firing is next Monday.
            fauxText('Weekly digest posted.'),
        ])

        const { application, revision } = await c.deployAgent({
            slug: 'kudos-bot',
            spec,
            files,
            encrypted_env: { SLACK_SIGNING_SECRET: SLACK_SECRET },
        })

        // Seed last week's (2026-W23) kudos so the digest query finds rows.
        const scope = { teamId: 1, applicationId: application.id }
        await c.tabularStore.append(scope, 'kudos', [
            {
                kudos_id: 'slack:C-kudos:a:<@U-jane>',
                recipient_handle: '<@U-jane>',
                giver_handle: '<@U-ben>',
                message: 'unblocked the migration',
                week: '2026-W23',
                source: 'slack',
            },
            {
                kudos_id: 'slack:C-kudos:b:<@U-jane>',
                recipient_handle: '<@U-jane>',
                giver_handle: '<@U-raj>',
                message: 'thorough PR review',
                week: '2026-W23',
                source: 'slack',
            },
            {
                kudos_id: 'slack:C-kudos:c:<@U-raj>',
                recipient_handle: '<@U-raj>',
                giver_handle: '<@U-jane>',
                message: 'paired on the flaky test',
                week: '2026-W23',
                source: 'slack',
            },
        ])

        // Fire the cron tick — the janitor's setInterval does this in prod.
        // The schedule is `0 9 * * 1` (Monday 09:00) in America/Los_Angeles;
        // 2026-06-08 is a Monday and 09:00 PDT = 16:00 UTC. Window is
        // (lastTickAt, now], so t0 must land strictly before the firing.
        const state = newCronTickState()
        const deps = { revisions: c.revisions, queue: c.queue, encryption: c.encryption }
        const t0 = new Date('2026-06-08T15:59:00Z') // 08:59 PT — seeds the window
        await cronTick({ ...deps, now: () => t0 }, state)
        const t1 = new Date('2026-06-08T16:01:00Z') // window (15:59, 16:01] catches 16:00
        const r1 = await cronTick({ ...deps, now: () => t1 }, state)
        expect(r1.fired).toBe(1)
        expect(r1.errors).toBe(0)

        await c.drain({ iterations: 100 })

        const minute = Math.floor(new Date('2026-06-08T16:00:00Z').getTime() / 60_000)
        const session = await c.queue.findByIdempotencyKey(
            application.id,
            `cron:${revision.id}:weekly-kudos-summary:${minute}`
        )
        expect(session).not.toBeNull()
        expect(session!.state).toBe('completed')
        expect(session!.trigger_metadata).toMatchObject({
            kind: 'cron',
            cron_name: 'weekly-kudos-summary',
        })

        const calledTools = session!.conversation
            .filter((m) => m.role === 'toolResult')
            .map((m) => (m as { toolName?: string }).toolName)
        expect(calledTools).toEqual(['@posthog/load-skill', '@posthog/table-query', '@posthog/slack-post-message'])

        // The digest actually went out to the kudos channel via the native
        // slack tool (token substitution + Slack Web API call fired).
        const posts = slackCalls.filter((s) => s.method === 'chat.postMessage')
        expect(posts).toHaveLength(1)
        expect(posts[0].auth).toBe('Bearer xoxb-faux')
        expect(posts[0].body.channel).toBe('C-kudos')
        expect(String(posts[0].body.text)).toContain('Kudos — week of')
    })
})
