/**
 * Example bundle e2e — `services/agent-tests/src/examples/sre-slack-bot/`.
 *
 * Loads the bundle from disk, deploys it through the harness, and
 * drives a realistic alert flow with the faux model. The point is
 * a regression net: if the bundle's spec.json or skill paths drift
 * out of sync with what the runner / tool registry expect, this
 * case fails before the bundle reaches production.
 *
 * NOT a real-inference test — the model is faux; the assertions
 * are about wiring, not about whether the agent's prose is good.
 */

import { readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import request from 'supertest'

import { serializeMemoryDoc } from '@posthog/agent-shared'

import { buildCluster, closeSharedPool, Cluster, fakeAuthProvider, fauxCallTool, fauxText } from '../harness'

const WEBHOOK_SECRET = 'sre-test-webhook-secret'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BUNDLE_ROOT = resolve(__dirname, '../examples/sre-slack-bot')
const BUNDLE_FILES = [
    'agent.md',
    'skills/triage-playbook/SKILL.md',
    'skills/slack-thread-protocol/SKILL.md',
    'skills/incident-io-playbook/SKILL.md',
    'skills/runbook-memory/SKILL.md',
] as const

async function loadBundle(): Promise<{ spec: Record<string, unknown>; files: Record<string, string> }> {
    const spec = JSON.parse(await readFile(join(BUNDLE_ROOT, 'spec.json'), 'utf-8')) as Record<string, unknown>
    const files: Record<string, string> = {}
    for (const path of BUNDLE_FILES) {
        files[path] = await readFile(join(BUNDLE_ROOT, path), 'utf-8')
    }
    return { spec, files }
}

describe('example: sre-slack-bot bundle', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster({
            // Bundle uses bring-your-own Slack via `@posthog/http-request` +
            // a `SLACK_BOT_TOKEN` secret — the runner substitutes the value
            // into `Authorization: Bearer ${SLACK_BOT_TOKEN}` before dispatch.
            // No platform-managed Slack integration is needed.
            resolveSecrets: async () => ({
                SLACK_BOT_TOKEN: 'xoxb-test-token',
                SLACK_SIGNING_SECRET: 'test-signing-secret',
            }),
            authProvider: fakeAuthProvider({ shared: WEBHOOK_SECRET }),
        })
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('loads cleanly — spec parses, every skill path resolves to a bundle file', async () => {
        const { spec, files } = await loadBundle()
        // Sanity: every skill path referenced in spec.skills[] is also a file
        // we shipped. Drift between the two is the most common bundle bug.
        const skillPaths = (spec.skills as Array<{ path: string }>).map((s) => s.path)
        for (const p of skillPaths) {
            expect(files[p]).not.toBeUndefined()
        }
        // agent.md is the default entrypoint and must exist.
        expect(files['agent.md']).not.toBeUndefined()
        expect(files['agent.md'].length).toBeGreaterThan(200)
    })

    it('routes a Slack DM into a session — allow_direct_messages bypasses mention_only', async () => {
        const { spec, files } = await loadBundle()
        c.setScript([fauxText('On it — pulling up the ingestion alert now.')])
        // Signing secret must live in the agent's encrypted_env: the slack guard
        // resolves SLACK_SIGNING_SECRET there (the cluster `resolveSecrets` path
        // is session-time, for ${SLACK_BOT_TOKEN} substitution on the runner).
        await c.deployAgent({
            slug: 'sre-slack-bot',
            spec,
            files,
            encrypted_env: { SLACK_SIGNING_SECRET: 'test-signing-secret' },
        })

        // A 1:1 DM (channel_type "im"), no @-mention. The bundle sets
        // mention_only: true, so without allow_direct_messages this would be
        // dropped — a DM is inherently directed at the bot. `team` must match
        // the bundle's trusted_workspaces or the workspace gate 403s.
        const dm = {
            type: 'event_callback',
            event_id: 'Ev_dm_1',
            event: {
                type: 'message',
                channel: 'D01',
                channel_type: 'im',
                user: 'U_oncall',
                team: 'TSS5W8YQZ',
                text: "what's the status of the ingestion alert?",
                ts: '1700000100.000100',
            },
        }
        const res = await c.slackPost('sre-slack-bot', 'events', dm, 'test-signing-secret')
        expect(res.status).toBe(200)
        expect(res.body.dropped).toBeUndefined()
        expect(res.body.session_id).toBeTruthy()

        await c.drain()
        const session = await c.queue.get(res.body.session_id as string)
        // DMs key per-channel — one rolling session per conversation.
        expect(session!.external_key).toBe('slack:D01')
        const userMsg = session!.conversation.find((m) => m.role === 'user') as { content: string } | undefined
        expect(userMsg?.content).toMatch(/^dm: true$/m)
        expect(userMsg?.content).toContain('ingestion alert')
    })

    it('deploys end-to-end and runs through a webhook-driven triage flow using bring-your-own Slack token', async () => {
        const { spec, files } = await loadBundle()

        // Track every Slack-bound request the agent made so we can prove the
        // bearer header was stamped (i.e. ${SLACK_BOT_TOKEN} substitution
        // actually fired on the runner side) and the JSON body was shaped
        // correctly for the Slack Web API. The recorder replaces the runner's
        // HttpClient — bare global.fetch wouldn't intercept anymore now that
        // tools dispatch through `ctx.http.fetch`.
        const slackCalls: Array<{ url: string; method?: string; auth?: string; body?: unknown }> = []
        const recorderHttp = {
            fetch: (input: string | URL, init?: RequestInit): Promise<Response> => {
                const url = typeof input === 'string' ? input : input.toString()
                if (url.includes('slack.com/api/')) {
                    const headers = (init?.headers ?? {}) as Record<string, string>
                    slackCalls.push({
                        url,
                        method: init?.method,
                        auth: headers.Authorization,
                        body: typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body,
                    })
                    return Promise.resolve({
                        ok: true,
                        status: 200,
                        json: async () => ({ ok: true, ts: '1700000050.000200', channel: 'C01' }),
                        text: async () => JSON.stringify({ ok: true, ts: '1700000050.000200', channel: 'C01' }),
                        headers: new Map([['content-type', 'application/json']]),
                    } as unknown as Response)
                }
                if (url.includes('runbooks.internal')) {
                    return Promise.resolve({
                        ok: true,
                        status: 200,
                        text: async () => '# Runbook: ingest 500s\nCheck kafka consumer lag.',
                        headers: new Map([['content-type', 'text/markdown']]),
                    } as unknown as Response)
                }
                return Promise.resolve({
                    ok: true,
                    status: 200,
                    text: async () => '{}',
                    headers: new Map(),
                } as unknown as Response)
            },
        }
        // Rebuild the cluster with the http recorder. The default cluster
        // (from beforeEach) carries the real HttpClient; we tear it down and
        // start fresh so the runner threads the recorder into ToolContext.http.
        await c.teardown()
        c = await buildCluster({
            resolveSecrets: async () => ({
                SLACK_BOT_TOKEN: 'xoxb-test-token',
                SLACK_SIGNING_SECRET: 'test-signing-secret',
            }),
            authProvider: fakeAuthProvider({ shared: WEBHOOK_SECRET }),
            http: recorderHttp,
        })

        // The faux model's script — same triage flow as before, but every
        // Slack tool call now goes through `@posthog/http-request` against
        // `https://slack.com/api/<method>` with `${SLACK_BOT_TOKEN}` in the
        // Authorization header. The runner substitutes the secret before
        // dispatch, so the raw header here is the placeholder; the captured
        // fetch headers above prove the substitution fired.
        c.setScript([
            // Phase 1: react to acknowledge.
            fauxCallTool('@posthog/http-request', {
                url: 'https://slack.com/api/reactions.add',
                method: 'POST',
                headers: { Authorization: 'Bearer ${SLACK_BOT_TOKEN}' },
                body: { channel: 'C-incidents', timestamp: '1700000099.000000', name: 'eyes' },
            }),
            // Phase 2: check prior incidents for this alert signature.
            fauxCallTool('@posthog/table-query', {
                table: 'incidents',
                where: { alert_signature: 'ingestion-500s' },
                limit: 5,
            }),
            // NOTE: incident.io is now reached through its MCP (`mcps[incident-io]`),
            // not raw HTTP. The bundle ships a PLACEHOLDER connection that won't open
            // in this harness, so the incident.io tools (incident_list / incident_show /
            // incident_update / …) aren't exercised here — the bot degrades to the
            // Slack-only flow. Coverage of the MCP-mediated path belongs in a case that
            // stands up a connected MCP.
            // Phase 3: load the triage skill.
            fauxCallTool('@posthog/load-skill', { id: 'triage-playbook' }),
            // Phase 4: read the channel for context.
            fauxCallTool('@posthog/http-request', {
                url: 'https://slack.com/api/conversations.history',
                method: 'POST',
                headers: { Authorization: 'Bearer ${SLACK_BOT_TOKEN}' },
                body: { channel: 'C-incidents', limit: 20 },
            }),
            // Phase 5: fetch the runbook.
            fauxCallTool('@posthog/http-request', {
                url: 'https://runbooks.internal/ingestion-500s',
            }),
            // Phase 6: load the reply-protocol skill.
            fauxCallTool('@posthog/load-skill', { id: 'slack-thread-protocol' }),
            // Phase 7: post the final analysis.
            fauxCallTool('@posthog/http-request', {
                url: 'https://slack.com/api/chat.postMessage',
                method: 'POST',
                headers: { Authorization: 'Bearer ${SLACK_BOT_TOKEN}' },
                body: {
                    channel: 'C-incidents',
                    thread_ts: '1700000099.000000',
                    text: ':mag: *TL;DR:* ingest 500s correlate with kafka consumer lag.\n\n*Suggested next step* cc oncall',
                },
            }),
            // Phase 8a: record the resolved outcome so future alerts can
            // short-circuit. Dedupe on thread_url.
            fauxCallTool('@posthog/table-append', {
                table: 'incidents',
                rows: [
                    {
                        alert_signature: 'ingestion-500s',
                        symptom: 'ingest 500s spike',
                        root_cause: 'kafka consumer lag',
                        mitigation: 'scaled consumer group, lag drained in 4m',
                        thread_url: 'https://slack.com/archives/C-incidents/p1700000099000000',
                        resolved_at: '2026-05-29T15:10:00Z',
                        incident_io_id: '01HXYZ',
                    },
                ],
                dedupe_on: 'thread_url',
            }),
            // Close the turn.
            fauxText('Triage posted, outcome recorded, ending session.'),
        ])

        await c.deployAgent({ slug: 'sre-slack-bot', spec, files })
        const alertPayload = {
            alerts: [
                {
                    labels: { alertname: 'Ingestion500s', severity: 'critical' },
                    annotations: { runbook_url: 'https://runbooks.internal/ingestion-500s' },
                    startsAt: '2026-05-29T14:32:00Z',
                    value: '4.7',
                },
            ],
        }
        // The example bundle's webhook is gated by spec.auth.modes — the
        // shared_secret mode expects the value in the `X-Webhook-Secret`
        // header. Production callers (incident.io webhook config, Grafana
        // alertmanager headers, …) set this verbatim.
        const res = await request(c.ingress)
            .post('/agents/sre-slack-bot/webhook')
            .set('x-webhook-secret', WEBHOOK_SECRET)
            .send(alertPayload)
        expect(res.status).toBe(200)
        await c.drain({ iterations: 100 })

        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')

        const calledTools = session!.conversation
            .filter((m) => m.role === 'toolResult')
            .map((m) => (m as { toolName?: string }).toolName)
        expect(calledTools).toEqual([
            '@posthog/http-request', // reactions.add (slack)
            '@posthog/table-query',
            '@posthog/load-skill', // triage-playbook
            '@posthog/http-request', // conversations.history (slack)
            '@posthog/http-request', // runbook fetch
            '@posthog/load-skill', // slack-thread-protocol
            '@posthog/http-request', // chat.postMessage (slack)
            '@posthog/table-append',
        ])

        // Prove the bring-your-own-token wiring actually fired. The agent's
        // tool calls reference `${SLACK_BOT_TOKEN}`; we expect the runner to
        // have substituted the resolved value before each request went out.
        // Captured fetch headers should NEVER contain the literal placeholder.
        expect(slackCalls).toHaveLength(3)
        for (const call of slackCalls) {
            expect(call.method).toBe('POST')
            expect(call.auth).toBe('Bearer xoxb-test-token')
            expect(call.auth).not.toContain('${') // no unsubstituted placeholders
        }
        // Spot-check the three Slack endpoints we expected to hit.
        const endpoints = slackCalls.map((c) => c.url.replace('https://slack.com/api/', '')).sort()
        expect(endpoints).toEqual(['chat.postMessage', 'conversations.history', 'reactions.add'])

        // Confirm the row actually landed in the tabular store — proves the
        // tool wired through to a real S3 backend, not just executed in a vacuum.
        const rows = await c.tabularStore.query(
            { teamId: session!.team_id, applicationId: session!.application_id },
            'incidents',
            { where: { alert_signature: 'ingestion-500s' } }
        )
        expect(rows).toHaveLength(1)
        expect(rows[0]).toMatchObject({
            alert_signature: 'ingestion-500s',
            mitigation: 'scaled consumer group, lag drained in 4m',
        })
    })

    it('reads the runbook corpus during triage and proposes an approval-gated runbook update', async () => {
        const { spec, files } = await loadBundle()

        const SEED_RUNBOOK = 'runbooks/systems/ingestion.md'
        const NEW_RUNBOOK = 'runbooks/alerts/ingestion-500s.md'
        const proposedContent =
            '# Alert: ingestion-500s\n\n' +
            '**What it means:** the ingestion pipeline is returning 500s to capture.\n\n' +
            '## First checks\n1. Kafka consumer lag on `events-main`.\n\n' +
            '## Known causes\n- Kafka consumer lag after a deploy. Mitigation: scale the consumer group. (seen 2026-05-29)\n'

        c.setScript([
            // Consult the corpus first — reads are open (no approval).
            fauxCallTool('@posthog/load-skill', { id: 'runbook-memory' }),
            fauxCallTool('@posthog/memory-search', { cue: 'ingestion 500s kafka lag', prefix: 'runbooks/' }),
            fauxCallTool('@posthog/memory-read', { path: SEED_RUNBOOK }),
            // Propose a brand-new alert runbook — APPROVAL-GATED, so this queues
            // a synthetic envelope instead of writing.
            fauxCallTool('@posthog/memory-write', {
                path: NEW_RUNBOOK,
                description: 'Alert runbook: ingestion 500s — kafka consumer lag is the usual cause',
                content: proposedContent,
                tags: ['ingestion', 'kafka', 'alert'],
            }),
            // Model reacts to the queued envelope: link the human to approve.
            fauxText(
                'Drafted a runbook for ingestion-500s and queued it for approval — approve at the link to save it.'
            ),
            // After the approval wake, wrap up.
            fauxText('Runbook approved and saved — future ingestion-500s alerts will short-circuit.'),
        ])

        const { application } = await c.deployAgent({ slug: 'sre-slack-bot', spec, files })
        const scope = { teamId: 1, applicationId: application.id }

        // Seed a system runbook so the corpus read returns real content.
        await c.memoryStore.put(
            scope,
            SEED_RUNBOOK,
            serializeMemoryDoc({
                description: 'How the ingestion pipeline works — Kafka → plugin-server → ClickHouse',
                tags: ['ingestion', 'system'],
                content: '# Ingestion pipeline\n\nKafka → plugin-server → ClickHouse. Owner: #team-ingestion.\n',
                createdAt: '2026-05-01T00:00:00.000Z',
                updatedAt: '2026-05-01T00:00:00.000Z',
            })
        )

        const res = await request(c.ingress)
            .post('/agents/sre-slack-bot/webhook')
            .set('x-webhook-secret', WEBHOOK_SECRET)
            .send({ alerts: [{ labels: { alertname: 'Ingestion500s' } }] })
        expect(res.status).toBe(200)
        const sessionId = res.body.session_id as string
        await c.drain({ iterations: 100 })

        // The gated write did NOT land — the proposed runbook is still absent.
        expect(await c.memoryStore.exists(scope, NEW_RUNBOOK)).toBe(false)

        // The model received a queued envelope carrying an approval URL, not a write.
        const session = await c.queue.get(sessionId)
        const queued = findApprovalPayload(session!.conversation)
        expect(queued).not.toBeNull()
        expect(queued!.approval_url).toMatch(/\/approvals\?request=/)

        // Exactly one queued approval for the memory-write, queryable via janitor.
        const listed = await request(c.janitor)
            .get('/approvals')
            .query({ application_id: application.id, state: 'queued' })
        expect(listed.status).toBe(200)
        const queuedRows = listed.body.results as Array<{ id: string; tool_name: string }>
        expect(queuedRows).toHaveLength(1)
        expect(queuedRows[0].tool_name).toBe('@posthog/memory-write')

        // Approve it — the runbook lands in real memory on dispatch.
        const decided = await request(c.janitor)
            .post(`/approvals/${queuedRows[0].id}/decide`)
            .send({ decision: 'approve', decided_by: '00000000-0000-0000-0000-000000000009' })
        expect(decided.status).toBe(200)
        await c.drain({ iterations: 100 })

        const landed = await c.memoryStore.read(scope, NEW_RUNBOOK)
        expect(landed.content).toContain('Kafka consumer lag')
        expect(landed.frontmatter.description).toContain('ingestion 500s')
    })
})

/**
 * Pull the synthetic queued-approval envelope out of a conversation — the
 * dispatcher lands it as a `toolResult` carrying `{ approval: { state, … } }`
 * instead of the real tool result. Mirrors the helper in approval-gated cases.
 */
function findApprovalPayload(
    conversation: unknown[]
): { request_id: string; state: string; approval_url?: string } | null {
    for (const msg of conversation) {
        const m = msg as { role?: string; content?: string | Array<{ type?: string; text?: string }> }
        if (m.role !== 'toolResult' && m.role !== 'user') {
            continue
        }
        const text = Array.isArray(m.content) ? m.content[0]?.text : typeof m.content === 'string' ? m.content : null
        if (typeof text !== 'string') {
            continue
        }
        try {
            const parsed = JSON.parse(text)
            if (parsed?.approval?.state === 'queued') {
                return parsed.approval
            }
        } catch {
            // not a JSON envelope
        }
    }
    return null
}
