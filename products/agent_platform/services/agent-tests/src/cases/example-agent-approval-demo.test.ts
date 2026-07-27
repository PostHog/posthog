/**
 * Example bundle e2e — `services/agent-tests/src/examples/agent-approval-demo/`.
 *
 * Smallest possible agent that demonstrates the approval gate. This case
 * loads the bundle from disk, deploys it through the harness, drives a
 * realistic chat turn end-to-end:
 *
 *   user "save 'hello'" → model proposes memory-write → dispatcher
 *     intercepts → synthetic queued envelope lands in the conversation →
 *   list approval via janitor → POST /approvals/:id/decide → runner picks
 *     up the wake marker → dispatches the real memory-write → memory file
 *     lands in real S3/SeaweedFS → synthetic approved envelope lands in
 *     the conversation → model emits closing text.
 *
 * Drift in any of those steps lights up here first. The bundle's value
 * is also surfaced via the approvals UI; the screen-side
 * regression net is Storybook.
 */

import { readdir, readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import request from 'supertest'

import { AgentSpecSchema } from '@posthog/agent-shared'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BUNDLE_ROOT = resolve(__dirname, '../examples/agent-approval-demo')

async function loadBundle(): Promise<{ spec: Record<string, unknown>; files: Record<string, string> }> {
    const spec = JSON.parse(await readFile(join(BUNDLE_ROOT, 'spec.json'), 'utf-8')) as Record<string, unknown>
    const files: Record<string, string> = {}
    files['agent.md'] = await readFile(join(BUNDLE_ROOT, 'agent.md'), 'utf-8')
    const skillDirs = await readdir(join(BUNDLE_ROOT, 'skills'))
    for (const id of skillDirs) {
        const p = `skills/${id}/SKILL.md`
        files[p] = await readFile(join(BUNDLE_ROOT, p), 'utf-8')
    }
    return { spec, files }
}

interface ApprovalRow {
    id: string
    state: string
    tool_name: string
    proposed_args: Record<string, unknown>
}

describe('example: agent-approval-demo bundle', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster()
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    // ── Static checks: the bundle is internally consistent ───────────

    it('every skill path in spec.skills[] exists as a bundle file', async () => {
        const { spec, files } = await loadBundle()
        for (const skill of spec.skills as Array<{ path: string; description: string }>) {
            expect(files[skill.path]).not.toBeUndefined()
            expect(skill.description.length).toBeGreaterThan(30)
        }
    })

    it('agent.md is present and non-trivial', async () => {
        const { files } = await loadBundle()
        expect(files['agent.md']).not.toBeUndefined()
        expect(files['agent.md'].length).toBeGreaterThan(500)
    })

    it('memory-write is the one gated tool; memory-read / memory-search are open', async () => {
        const { spec } = await loadBundle()
        const tools = spec.tools as Array<{
            id: string
            requires_approval?: boolean
            approval_policy?: {
                type?: string
                allow_edit?: boolean
                ttl_ms?: number
            }
        }>
        const write = tools.find((t) => t.id === '@posthog/memory-write')
        expect(write).toBeTruthy()
        expect(write!.requires_approval).toBe(true)
        // `agent` — the agent's owners (team admins) approve in the console.
        expect(write!.approval_policy?.type).toBe('agent')
        // allow_edit so the console drawer surfaces the JSON editor.
        expect(write!.approval_policy?.allow_edit).toBe(true)

        for (const id of ['@posthog/memory-read', '@posthog/memory-search']) {
            const open = tools.find((t) => t.id === id)
            expect(open).toBeTruthy()
            expect(open!.requires_approval).not.toBe(true)
        }
    })

    it('the spec parses through AgentSpecSchema — runner accepts it as-is', async () => {
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        const write = parsed.tools.find((t) => 'id' in t && t.id === '@posthog/memory-write') as
            | { requires_approval?: boolean; approval_policy?: { allow_edit?: boolean } }
            | undefined
        expect(write).toBeTruthy()
        expect(write!.requires_approval).toBe(true)
        expect(write!.approval_policy?.allow_edit).toBe(true)
    })

    it('the shared example seeder exists with the deploy primitives intact', async () => {
        // One generic seeder serves every example bundle; it auto-discovers
        // any dir holding spec.json + agent.md (this bundle qualifies — proven
        // by loadBundle above) and runs the full deploy pipeline per bundle.
        const scriptPath = resolve(__dirname, '../examples/seed.py')
        const src = await readFile(scriptPath, 'utf-8')
        expect(src.startsWith('#!/usr/bin/env python3')).toBe(true)
        expect(src).toContain('def per_file_sha256(')
        expect(src).toContain('def load_v0_spec(')
        expect(src).toContain('def discover_bundles(')
    })

    // ── End-to-end run-through: queue → approve → real dispatch ──────

    it('queues a real memory-write through the gate, approves, dispatches, ends the session', async () => {
        const { spec, files } = await loadBundle()

        c.setScript([
            // Turn 1: model proposes the gated write.
            fauxCallTool('@posthog/memory-write', {
                path: 'notes/hello.md',
                description: 'first note',
                content: 'hello world',
            }),
            // Turn 2: model reacts to the synthetic queued result (would
            // typically tell the user where to approve). Session ends here
            // until the approval lands.
            fauxText('Queued your note for approval — I will confirm once it lands.'),
            // Turn 3: after approval wake, model wraps up.
            fauxText('Saved. The note is now in memory.'),
        ])

        const { application, revision } = await c.deployAgent({
            slug: 'agent-approval-demo',
            spec,
            files,
        })

        const scope = { teamId: 1, applicationId: application.id }

        const run = await request(c.ingress).post('/agents/agent-approval-demo/run').send({ message: 'save hello' })
        expect(run.status).toBe(200)
        const sessionId = run.body.session_id as string

        await c.drain()

        // Session did NOT park — gates don't change state.
        let session = await c.queue.get(sessionId)
        expect(session).not.toBeNull()
        expect(session!.state).not.toBe('waiting')

        // The model received the synthetic queued envelope, not the real result.
        const queuedEnvelope = findApprovalPayload(session!.conversation, 'queued')
        expect(queuedEnvelope).not.toBeNull()
        expect(queuedEnvelope!.approval_url).toMatch(/\/approvals\?request=/)

        // The approval row is queryable via janitor — same surface the Django
        // proxy hits, same surface the console UI talks to.
        const queuedRows = await listApprovals(application.id, 'queued')
        expect(queuedRows).toHaveLength(1)
        expect(queuedRows[0].tool_name).toBe('@posthog/memory-write')
        expect(queuedRows[0].proposed_args).toMatchObject({
            path: 'notes/hello.md',
            description: 'first note',
            content: 'hello world',
        })

        // No memory file yet — the real dispatch hasn't happened.
        expect(await c.memoryStore.exists(scope, 'notes/hello.md')).toBe(false)

        // Approver decides via the janitor decide endpoint — same path Django
        // proxies via `agent-applications-approvals-decide`.
        await decide(queuedRows[0].id, {
            decision: 'approve',
            decided_by: '00000000-0000-0000-0000-000000000007',
        })

        await c.drain()

        session = await c.queue.get(sessionId)
        expect(session!.state).toBe('completed')

        // Memory file landed in real S3/SeaweedFS — proves the runner
        // executed the dispatch with the proposed args.
        const memoryFile = await c.memoryStore.read(scope, 'notes/hello.md')
        expect(memoryFile.content).toContain('hello world')

        // Approval row finalised to `dispatched`.
        const allRows = await listApprovals(application.id)
        const finalised = allRows.find((r) => r.id === queuedRows[0].id)
        expect(finalised?.state).toBe('dispatched')

        // The model's final assistant message lands as expected.
        const assistantMessages = session!.conversation.filter(
            (m) => (m as { role: string }).role === 'assistant'
        ) as Array<{ content: Array<{ type: string; text?: string }> }>
        const finalText = assistantMessages[assistantMessages.length - 1]
        expect(finalText.content[0].text).toBe('Saved. The note is now in memory.')

        // Application + revision are real rows the console can list.
        expect(application.id).toBeTruthy()
        expect(revision.id).toBeTruthy()
    })

    it('approve-with-edits dispatches the edited args, not the proposed args', async () => {
        const { spec, files } = await loadBundle()

        c.setScript([
            fauxCallTool('@posthog/memory-write', {
                path: 'notes/typo.md',
                description: 'with a typoo',
                content: 'badd content',
            }),
            fauxText('Queued for approval.'),
            fauxText('Saved with corrections.'),
        ])

        const { application } = await c.deployAgent({
            slug: 'agent-approval-demo-edit',
            spec,
            files,
        })
        const scope = { teamId: 1, applicationId: application.id }

        await request(c.ingress).post('/agents/agent-approval-demo-edit/run').send({ message: 'save typo' })
        await c.drain()

        const [pending] = await listApprovals(application.id, 'queued')
        expect(pending).toBeTruthy()

        await decide(pending.id, {
            decision: 'approve',
            decided_by: '00000000-0000-0000-0000-000000000008',
            edited_args: {
                path: 'notes/fixed.md',
                description: 'with corrections',
                content: 'good content',
            },
        })

        await c.drain()

        // Edited args ran — corrected file is what landed in S3, original
        // proposed path is empty.
        expect(await c.memoryStore.exists(scope, 'notes/typo.md')).toBe(false)
        const corrected = await c.memoryStore.read(scope, 'notes/fixed.md')
        expect(corrected.content).toContain('good content')
    })

    // ── Helpers ──────────────────────────────────────────────────────

    async function listApprovals(applicationId: string, state?: string): Promise<ApprovalRow[]> {
        const res = await request(c.janitor)
            .get('/approvals')
            .query({ application_id: applicationId, ...(state ? { state } : {}) })
        expect(res.status).toBe(200)
        return res.body.results as ApprovalRow[]
    }

    async function decide(
        approvalId: string,
        body: {
            decision: 'approve' | 'reject'
            decided_by: string
            edited_args?: Record<string, unknown>
            reason?: string
        }
    ): Promise<unknown> {
        const res = await request(c.janitor).post(`/approvals/${approvalId}/decide`).send(body)
        expect(res.status).toBe(200)
        return res.body
    }
})

/**
 * Pull the synthetic-approval envelope out of a conversation. Mirrors
 * the helper in `cases/approval-gated.test.ts`. The intercept's queued
 * result lands as a toolResult; the wake result lands as a user message.
 */
function findApprovalPayload(
    conversation: unknown[],
    state: 'queued' | 'approved' | 'rejected' | 'expired'
): { request_id: string; state: string; approval_url?: string; result?: unknown } | null {
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
            if (parsed?.approval?.state === state) {
                return {
                    ...parsed.approval,
                    ...(parsed.result !== undefined ? { result: parsed.result } : {}),
                }
            }
        } catch {
            // not a JSON envelope
        }
    }
    return null
}
