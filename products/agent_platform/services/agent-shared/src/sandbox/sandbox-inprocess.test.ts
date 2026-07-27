import { InProcessSandboxPool } from './sandbox-inprocess'

const SIMPLE_TOOL = `
module.exports = {
    id: "echo-tool",
    actions: {
        echo: async (args, ctx) => {
            return { you_said: args.message, secret_ref: ctx.secrets.ref("ACME_KEY") }
        },
        add: (args) => args.a + args.b,
        throws: () => { throw new Error("boom") },
        slow: async () => {
            await new Promise((r) => setTimeout(r, 1000))
            return "done"
        },
    },
}
`

describe('InProcessSandboxPool', () => {
    it('refuses to construct outside NODE_ENV=test', () => {
        // Guards against accidentally wiring the unsandboxed pool in dev /
        // prod — selectSandboxPool() is the boundary for those.
        const prev = process.env.NODE_ENV
        try {
            process.env.NODE_ENV = 'production'
            expect(() => new InProcessSandboxPool()).toThrow(/test-only/i)
            process.env.NODE_ENV = 'development'
            expect(() => new InProcessSandboxPool()).toThrow(/test-only/i)
            process.env.NODE_ENV = undefined
            expect(() => new InProcessSandboxPool()).toThrow(/test-only/i)
        } finally {
            process.env.NODE_ENV = prev
        }
    })

    it('loads a tool and runs an action', async () => {
        const pool = new InProcessSandboxPool()
        const sandbox = await pool.acquireForSession({
            sessionId: 's1',
            teamId: 1,
            tools: [{ id: 'echo-tool', compiledJs: SIMPLE_TOOL, schemaJson: {} }],
            nonces: { ACME_KEY: 'nonce_xyz' },
        })
        const out = await sandbox.invoke({ toolId: 'echo-tool', action: 'echo', args: { message: 'hi' } })
        expect(out).toEqual({ ok: true, result: { you_said: 'hi', secret_ref: 'nonce_xyz' } })
        await pool.release('s1')
    })

    it('reuses sandbox for the same session', async () => {
        const pool = new InProcessSandboxPool()
        const a = await pool.acquireForSession({
            sessionId: 's2',
            teamId: 1,
            tools: [{ id: 'echo-tool', compiledJs: SIMPLE_TOOL, schemaJson: {} }],
            nonces: {},
        })
        const b = await pool.acquireForSession({
            sessionId: 's2',
            teamId: 1,
            tools: [{ id: 'echo-tool', compiledJs: SIMPLE_TOOL, schemaJson: {} }],
            nonces: {},
        })
        expect(a).toBe(b)
        await pool.release('s2')
    })

    it('returns ok:false on missing tool / action', async () => {
        const pool = new InProcessSandboxPool()
        const sandbox = await pool.acquireForSession({
            sessionId: 's3',
            teamId: 1,
            tools: [{ id: 'echo-tool', compiledJs: SIMPLE_TOOL, schemaJson: {} }],
            nonces: {},
        })
        const missingTool = await sandbox.invoke({ toolId: 'ghost', action: 'x', args: {} })
        expect(missingTool.ok).toBe(false)
        const missingAction = await sandbox.invoke({ toolId: 'echo-tool', action: 'nope', args: {} })
        expect(missingAction.ok).toBe(false)
        await pool.release('s3')
    })

    it('captures thrown exceptions', async () => {
        const pool = new InProcessSandboxPool()
        const sandbox = await pool.acquireForSession({
            sessionId: 's4',
            teamId: 1,
            tools: [{ id: 'echo-tool', compiledJs: SIMPLE_TOOL, schemaJson: {} }],
            nonces: {},
        })
        const out = await sandbox.invoke({ toolId: 'echo-tool', action: 'throws', args: {} })
        expect(out.ok).toBe(false)
        expect(out.ok ? '' : out.error.message).toContain('boom')
        await pool.release('s4')
    })

    it('enforces timeoutMs', async () => {
        const pool = new InProcessSandboxPool()
        const sandbox = await pool.acquireForSession({
            sessionId: 's5',
            teamId: 1,
            tools: [{ id: 'echo-tool', compiledJs: SIMPLE_TOOL, schemaJson: {} }],
            nonces: {},
        })
        const out = await sandbox.invoke({ toolId: 'echo-tool', action: 'slow', args: {}, timeoutMs: 50 })
        expect(out.ok).toBe(false)
        expect(out.ok ? '' : out.error.code).toBe('timeout')
        await pool.release('s5')
    })

    it('synchronous action result is wrapped in ok', async () => {
        const pool = new InProcessSandboxPool()
        const sandbox = await pool.acquireForSession({
            sessionId: 's6',
            teamId: 1,
            tools: [{ id: 'echo-tool', compiledJs: SIMPLE_TOOL, schemaJson: {} }],
            nonces: {},
        })
        const out = await sandbox.invoke({ toolId: 'echo-tool', action: 'add', args: { a: 2, b: 40 } })
        expect(out).toEqual({ ok: true, result: 42 })
        await pool.release('s6')
    })
})
