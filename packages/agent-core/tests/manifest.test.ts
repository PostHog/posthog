import { parseManifest } from '../src'

describe('parseManifest', () => {
    it('accepts a minimal valid manifest', () => {
        const result = parseManifest({
            name: 'greet',
            entrypoint: 'src/main.ts',
        })
        expect(result.errors).toEqual([])
        expect(result.manifest).toMatchObject({
            name: 'greet',
            entrypoint: 'src/main.ts',
            tools: [],
            triggers: [],
        })
    })

    it('rejects unknown built-in tool ids', () => {
        const result = parseManifest({
            name: 'broken',
            entrypoint: 'src/main.ts',
            tools: [{ id: 'not.a.real.tool' }],
        })
        expect(result.manifest).toBeNull()
        expect(result.errors).toEqual([
            expect.objectContaining({ path: 'tools.0.id', message: expect.stringMatching(/unknown built-in tool id/) }),
        ])
    })

    it('reports zod validation errors with paths', () => {
        const result = parseManifest({
            entrypoint: 'src/main.ts',
            triggers: [{ kind: 'http', path: 'no-leading-slash' }],
        })
        expect(result.manifest).toBeNull()
        expect(result.errors.length).toBeGreaterThan(0)
        const paths = result.errors.map((e) => e.path)
        expect(paths).toEqual(expect.arrayContaining(['name', 'triggers.0.path']))
    })

    it('accepts a manifest with builtins and triggers', () => {
        const result = parseManifest({
            name: 'analytics-bot',
            entrypoint: 'src/main.ts',
            tools: [{ id: 'posthog.events.capture' }],
            triggers: [
                { kind: 'http', path: '/hello' },
                { kind: 'cron', schedule: '0 * * * *' },
            ],
        })
        expect(result.errors).toEqual([])
        expect(result.manifest?.tools).toHaveLength(1)
        expect(result.manifest?.triggers).toHaveLength(2)
    })
})
