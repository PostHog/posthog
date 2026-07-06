/**
 * Custom tool sandbox: agent has a TS-source custom tool in its bundle,
 * faux model emits a toolCall for it, runner spins up the sandbox preloaded
 * with the compiled.js, dispatches the invoke. Old equivalent: tool-sandbox.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

const ECHOER_COMPILED = `
module.exports = {
    id: "echoer",
    actions: {
        default: (args) => ({ echoed: args.message ?? "(none)" }),
    },
}
`

const SECRET_USER_COMPILED = `
module.exports = {
    id: "secret-user",
    actions: {
        default: (args, ctx) => {
            // Secrets are nonces inside the sandbox — never raw values.
            const nonce = ctx.secrets.ref("ACME_API_KEY")
            return { token_header: \`Bearer \${nonce}\` }
        },
    },
}
`

describe('custom tool sandbox: real e2e', () => {
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

    it('agent calling a custom tool dispatches through the sandbox', async () => {
        c.setScript([fauxCallTool('echoer', { message: 'hi' }), fauxText('done')])
        await c.deployAgent({
            slug: 'echoer-agent',
            spec: {
                tools: [{ kind: 'custom', id: 'echoer', path: 'tools/echoer/' }],
            },
            files: {
                'agent.md': 'echo agent',
                'tools/echoer/source.ts': '// source',
                'tools/echoer/compiled.js': ECHOER_COMPILED,
                'tools/echoer/schema.json': JSON.stringify({
                    description: 'echoes its input',
                    args: { type: 'object' },
                }),
            },
        })
        const res = await request(c.ingress).post('/agents/echoer-agent/run').send({ message: 'fire' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // Conversation: user + assistant(toolCall) + toolResult + assistant(text)
        const toolResult = session!.conversation[2] as unknown as {
            role: 'toolResult'
            content: Array<{ type: string; text: string }>
        }
        expect(toolResult.role).toBe('toolResult')
        const resultText = toolResult.content[0].text
        expect(resultText).toContain('echoed')
        expect(resultText).toContain('hi')
    })

    it('tool-secret-broker: sandbox receives a nonce, not the raw secret', async () => {
        await c.teardown()
        c = await buildCluster({
            resolveSecrets: async () => ({ ACME_API_KEY: 'topsecret' }),
        })
        c.setScript([fauxCallTool('secret-user', {}), fauxText('done')])
        await c.deployAgent({
            slug: 'secret-agent',
            spec: {
                tools: [{ kind: 'custom', id: 'secret-user', path: 'tools/secret-user/' }],
                secrets: ['ACME_API_KEY'],
            },
            files: {
                'agent.md': 'x',
                'tools/secret-user/source.ts': '// source',
                'tools/secret-user/compiled.js': SECRET_USER_COMPILED,
                'tools/secret-user/schema.json': JSON.stringify({ description: 'uses a secret' }),
            },
        })
        const res = await request(c.ingress).post('/agents/secret-agent/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const toolResult = session!.conversation[2] as unknown as {
            role: 'toolResult'
            content: Array<{ type: string; text: string }>
        }
        const parsed = JSON.parse(toolResult.content[0].text) as { token_header: string }
        // Nonce shape: nonce_<hex>. Crucially, NOT the raw secret 'topsecret'.
        expect(parsed.token_header).toMatch(/^Bearer nonce_[a-f0-9]+$/)
        expect(parsed.token_header).not.toContain('topsecret')
    })

    it('writes a sandbox-instance row that traces provisioning → ready → terminated', async () => {
        c.setScript([fauxCallTool('echoer', { message: 'hi' }), fauxText('done')])
        const { application, revision } = await c.deployAgent({
            slug: 'tracked-agent',
            spec: {
                tools: [{ kind: 'custom', id: 'echoer', path: 'tools/echoer/' }],
            },
            files: {
                'agent.md': 'echo agent',
                'tools/echoer/source.ts': '// source',
                'tools/echoer/compiled.js': ECHOER_COMPILED,
                'tools/echoer/schema.json': JSON.stringify({ description: 'echoes', args: { type: 'object' } }),
            },
        })
        const res = await request(c.ingress).post('/agents/tracked-agent/run').send({ message: 'fire' })
        await c.drain()

        // The runner inserts the row at acquire and updates it at release —
        // by the time the session completes the row must be in `terminated`.
        const rows = await c.pool.query<{
            session_id: string
            state: string
            provider_kind: string
            provider_sandbox_id: string
            terminated_at: Date | null
        }>(
            `SELECT session_id::text, state, provider_kind, provider_sandbox_id, terminated_at
             FROM agent_sandbox_instance
             WHERE application_id = $1 AND revision_id = $2
             ORDER BY created_at ASC`,
            [application.id, revision.id]
        )
        expect(rows.rowCount).toBe(1)
        const row = rows.rows[0]
        expect(row.session_id).toBe(res.body.session_id)
        expect(row.state).toBe('terminated')
        expect(row.provider_kind).toBe('in-process')
        expect(row.provider_sandbox_id).toBe(res.body.session_id)
        expect(row.terminated_at).not.toBeNull()
    })

    it('does NOT write a sandbox-instance row when the agent has no custom tools', async () => {
        c.setScript([fauxText('hi back')])
        const { application } = await c.deployAgent({ slug: 'no-tools', spec: {} })
        await request(c.ingress).post('/agents/no-tools/run').send({ message: 'ping' })
        await c.drain()
        const rows = await c.pool.query(`SELECT 1 FROM agent_sandbox_instance WHERE application_id = $1`, [
            application.id,
        ])
        expect(rows.rowCount).toBe(0)
    })
})
