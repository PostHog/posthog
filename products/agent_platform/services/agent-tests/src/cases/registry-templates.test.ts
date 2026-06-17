/**
 * Registry-pinned skill / tool refs e2e.
 *
 * Agents author their `spec.skills[]` / `spec.tools[]` by referencing
 * registry templates (`from_template`), and Django's freeze action
 * resolves those refs into the bundle. Post-freeze the spec entries
 * still carry their `from_template` lineage (so the registry's "Used
 * by" panel works) AND the runtime fields the runner needs (`id`,
 * `path` for skills; the file paths for custom tools).
 *
 * The Django freeze logic lives in
 * `products/agent_platform/backend/registry_freeze.py`. This case proves
 * the runtime side accepts the post-freeze shape end-to-end:
 *
 *   1. zod parses a spec that carries `from_template` + `alias` +
 *      `version` alongside the runtime `id` / `path`.
 *   2. The runner's `@posthog/load-skill` tool reads the populated
 *      bundle as if Django had just frozen it.
 *
 * If this case fails on `AgentSpecSchema.parse`, the spec schema is
 * missing the post-freeze fields and the Django freeze flow would
 * collapse against the janitor's spec validator.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

describe('registry-pinned templates: real e2e', () => {
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

    it('spec carrying `from_template` + `alias` + `version` parses and loads through @posthog/load-skill', async () => {
        c.setScript([fauxCallTool('@posthog/load-skill', { id: 'research' }), fauxText('used the research skill')])
        await c.deployAgent({
            slug: 'registry-pinned-skill',
            spec: {
                skills: [
                    {
                        // Runtime-required fields — what `load-skill` resolves against.
                        id: 'research',
                        path: 'skills/research/SKILL.md',
                        description: 'How to research a question',
                        // Registry lineage — preserved post-freeze so the join table
                        // and the "Used by" panel can correlate.
                        from_template: '019e7fb7-f4c0-75e2-9055-7c29a5cbb923',
                        version: 3,
                        alias: 'research',
                    },
                ],
            },
            files: {
                'agent.md': 'you have a research skill (pinned from the registry).',
                // Mirrors what `registry_freeze.py` writes for an aliased skill:
                // a self-contained `skills/<alias>/` folder with SKILL.md at the root.
                'skills/research/SKILL.md': 'Step 1: ask questions. Step 2: cite sources.',
            },
        })
        const res = await request(c.ingress).post('/agents/registry-pinned-skill/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const toolResult = session!.conversation[2] as unknown as {
            role: 'toolResult'
            content: Array<{ text: string }>
        }
        const parsed = JSON.parse(toolResult.content[0].text) as { id: string; body: string }
        expect(parsed.id).toBe('research')
        expect(parsed.body).toContain('cite sources')
    })

    it('@posthog/load-skill reads a nested companion file inside the skill folder', async () => {
        // Progressive disclosure: SKILL.md points at a reference doc under a
        // subfolder; the model pulls it on demand with `file`. Proves the
        // runtime reads nested files in the spec's `skill/<dir>/...` layout.
        c.setScript([
            fauxCallTool('@posthog/load-skill', { id: 'research', file: 'references/deep.md' }),
            fauxText('read the deep reference'),
        ])
        await c.deployAgent({
            slug: 'registry-nested-skill',
            spec: {
                skills: [
                    {
                        id: 'research',
                        path: 'skills/research/SKILL.md',
                        description: 'How to research a question',
                        from_template: '019e7fb7-f4c0-75e2-9055-7c29a5cbb925',
                        version: 1,
                        alias: 'research',
                    },
                ],
            },
            files: {
                'agent.md': 'you have a research skill with reference docs.',
                'skills/research/SKILL.md': 'See references/deep.md for the deep dive.',
                'skills/research/references/deep.md': 'DEEP-MARKER: the full methodology.',
            },
        })
        const res = await request(c.ingress).post('/agents/registry-nested-skill/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const toolResult = session!.conversation[2] as unknown as {
            role: 'toolResult'
            content: Array<{ text: string }>
        }
        const parsed = JSON.parse(toolResult.content[0].text) as { id: string; path: string; body: string }
        expect(parsed.path).toBe('skills/research/references/deep.md')
        expect(parsed.body).toContain('DEEP-MARKER')
    })

    it('spec carrying a custom_template tool ref parses and dispatches the tool', async () => {
        // The runner reads custom tools from `bundle/tools/<alias>/{source.ts,compiled.js,schema.json}`
        // — same layout `registry_freeze.py` writes. compiled.js must export the
        // `{ id, actions: { ... } }` shape the InProcessSandbox expects.
        c.setScript([fauxCallTool('stripe_lookup', { email: 'a@b.co' }), fauxText('looked up the customer')])
        await c.deployAgent({
            slug: 'registry-pinned-tool',
            spec: {
                tools: [
                    {
                        // Runtime contract for custom tools.
                        kind: 'custom',
                        id: 'stripe_lookup',
                        path: 'tools/stripe_lookup/',
                        // Registry lineage.
                        from_template: '019e7fb7-f4c0-75e2-9055-7c29a5cbb924',
                        version: 4,
                        alias: 'stripe_lookup',
                    },
                ],
            },
            files: {
                'agent.md': 'use stripe_lookup to find customers.',
                'tools/stripe_lookup/source.ts': '// source elided',
                'tools/stripe_lookup/compiled.js': `
                    module.exports = {
                        id: 'stripe_lookup',
                        actions: {
                            default: (args) => ({ found: true, email: args.email }),
                        },
                    }
                `,
                'tools/stripe_lookup/schema.json': JSON.stringify({
                    description: 'Look up a customer by email',
                    args: {
                        type: 'object',
                        properties: { email: { type: 'string' } },
                        required: ['email'],
                    },
                }),
            },
        })
        const res = await request(c.ingress).post('/agents/registry-pinned-tool/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const toolResult = session!.conversation[2] as unknown as {
            role: 'toolResult'
            content: Array<{ text: string }>
        }
        const body = JSON.parse(toolResult.content[0].text) as { found?: boolean; email?: string }
        expect(body.found).toBe(true)
        expect(body.email).toBe('a@b.co')
    })
})
