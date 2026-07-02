import { getNativeTool, hasNativeTool, listNativeTools } from './registry'

describe('native tool registry', () => {
    it('exposes expected tools by id', () => {
        const ids = listNativeTools().map((t) => t.id)
        expect(ids).toEqual(
            expect.arrayContaining([
                '@posthog/query',
                '@posthog/slack-post-message',
                '@posthog/slack-update-message',
                '@posthog/slack-react',
                '@posthog/http-request',
                '@posthog/web-search',
                '@posthog/meta-end-turn',
                '@posthog/meta-end-session',
                '@posthog/meta-emit-event',
                '@posthog/load-skill',
            ])
        )
    })

    it('getNativeTool returns the tool', () => {
        const t = getNativeTool('@posthog/query')
        expect(t.id).toBe('@posthog/query')
        expect(t.schema.description).toMatch(/HogQL/)
    })

    it('getNativeTool throws on unknown id', () => {
        expect(() => getNativeTool('posthog.query.v999')).toThrow(/unknown native tool/)
    })

    it('hasNativeTool reflects availability', () => {
        expect(hasNativeTool('@posthog/slack-post-message')).toBe(true)
        expect(hasNativeTool('slack.post_message.v99')).toBe(false)
    })

    it("catalog entries don't expose the run function", () => {
        const entry = listNativeTools()[0]
        expect('run' in entry).toBe(false)
    })

    it('every tool has all required schema fields', () => {
        for (const t of listNativeTools()) {
            expect(t.schema.description.length).toBeGreaterThan(0)
            expect(t.schema.args).not.toBeUndefined()
            expect(t.schema.returns).not.toBeUndefined()
            // `requires.provider` is optional (omitted for credential-free tools);
            // when present it carries an id + scopes array.
            if (t.schema.requires.provider) {
                expect(typeof t.schema.requires.provider.id).toBe('string')
                expect(Array.isArray(t.schema.requires.provider.scopes)).toBe(true)
            }
            expect(['cheap', 'medium', 'expensive']).toContain(t.schema.cost_hint)
        }
    })
})
