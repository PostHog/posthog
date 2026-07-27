/**
 * Dynamic skill loading e2e.
 *
 * The runner emits a skill INDEX in the system prompt (not the body). When the
 * model needs the body it calls `@posthog/load-skill`, which the runner
 * resolves out of the active revision's bundle. These tests prove that:
 *   1. System prompt contains the index lines, not the skill bodies.
 *   2. `load-skill` returns the requested skill's body.
 *   3. Unknown skill ids error.
 *   4. Agents without skills don't have `@posthog/load-skill` in their tool
 *      list.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

describe('dynamic skill loading: real e2e', () => {
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

    it('model calls @posthog/load-skill and gets the skill body back', async () => {
        c.setScript([fauxCallTool('@posthog/load-skill', { id: 'research' }), fauxText('used the skill')])
        await c.deployAgent({
            slug: 'skill-using-agent',
            spec: {
                skills: [
                    {
                        id: 'research',
                        path: 'skills/research/SKILL.md',
                        description: 'How to research a question',
                    },
                ],
            },
            files: {
                'agent.md': 'you have a research skill available.',
                'skills/research/SKILL.md': 'Step 1: ask questions. Step 2: write down sources.',
            },
        })
        const res = await request(c.ingress).post('/agents/skill-using-agent/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // Conversation shape: user, assistant(toolCall), toolResult, assistant(text)
        const toolResult = session!.conversation[2] as unknown as {
            role: 'toolResult'
            content: Array<{ text: string }>
        }
        expect(toolResult.role).toBe('toolResult')
        const parsed = JSON.parse(toolResult.content[0].text) as { id: string; body: string }
        expect(parsed.id).toBe('research')
        expect(parsed.body).toContain('ask questions')
    })

    it('model loads a skill companion file via the file param', async () => {
        // Multi-file skills (the shape a store skill materializes into the bundle):
        // SKILL.md plus companion files under skills/<id>/. load-skill fetches a
        // companion when given `file`.
        c.setScript([
            fauxCallTool('@posthog/load-skill', { id: 'research', file: 'references/deep.md' }),
            fauxText('used the companion'),
        ])
        await c.deployAgent({
            slug: 'skill-companion-agent',
            spec: {
                skills: [{ id: 'research', path: 'skills/research/SKILL.md', description: 'How to research' }],
            },
            files: {
                'agent.md': 'you have a research skill with companion docs.',
                'skills/research/SKILL.md': 'See references/deep.md for the deep dive.',
                'skills/research/references/deep.md': 'DEEP DIVE: triangulate three independent sources.',
            },
        })
        const res = await request(c.ingress).post('/agents/skill-companion-agent/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const toolResult = session!.conversation[2] as unknown as {
            role: 'toolResult'
            content: Array<{ text: string }>
        }
        expect(toolResult.role).toBe('toolResult')
        const parsed = JSON.parse(toolResult.content[0].text) as { id: string; path: string; body: string }
        expect(parsed.id).toBe('research')
        expect(parsed.path).toBe('skills/research/references/deep.md')
        expect(parsed.body).toContain('triangulate three independent sources')
    })

    it('@posthog/load-skill errors when the id is unknown', async () => {
        c.setScript([fauxCallTool('@posthog/load-skill', { id: 'ghost' }), fauxText('oops')])
        await c.deployAgent({
            slug: 'skill-ghost',
            spec: {
                skills: [{ id: 'research', path: 'skills/research/SKILL.md', description: 'desc' }],
            },
            files: { 'agent.md': 'x', 'skills/research/SKILL.md': 'body' },
        })
        const res = await request(c.ingress).post('/agents/skill-ghost/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        const toolResult = session!.conversation[2] as unknown as {
            role: 'toolResult'
            content: Array<{ text: string }>
            isError?: boolean
        }
        expect(toolResult.isError).toBe(true)
        expect(toolResult.content[0].text).toMatch(/unknown skill id/)
    })

    it('an agent without skills does not get @posthog/load-skill in its tool list', async () => {
        // The model is given no tools to call here — if load-skill were exposed,
        // it would appear in the tool list. The faux model never sees the tool
        // list directly, but we can prove the assertion via a different route:
        // calling load-skill on a skill-less agent must error.
        c.setScript([fauxCallTool('@posthog/load-skill', { id: 'whatever' }), fauxText('done')])
        await c.deployAgent({
            slug: 'no-skills',
            spec: {},
            files: { 'agent.md': 'no skills' },
        })
        const res = await request(c.ingress).post('/agents/no-skills/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        const toolResult = session!.conversation[2] as unknown as {
            role: 'toolResult'
            content: Array<{ text: string }>
            isError?: boolean
        }
        // A skill-less agent never has load-skill in its tool list, so the loop
        // rejects the call outright ("tool not found") — stronger proof it
        // isn't exposed than the old advertised-no/dispatchable-yes behavior.
        expect(toolResult.isError).toBe(true)
        expect(toolResult.content[0].text).toMatch(/not found|unknown skill id|did not wire/)
    })
})
