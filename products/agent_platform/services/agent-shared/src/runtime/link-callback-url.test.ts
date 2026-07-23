import { buildLinkCallbackUrl } from './link-callback-url'

describe('buildLinkCallbackUrl', () => {
    it('domain mode lands on the agent’s own per-slug host', () => {
        expect(
            buildLinkCallbackUrl({
                routingMode: 'domain',
                domainSuffix: '.agents.us.posthog.com',
                slug: 'weekly-digest',
                provider: 'posthog',
            })
        ).toBe('https://weekly-digest.agents.us.posthog.com/link/posthog/callback')
    })

    it('path mode uses the flat public base URL with no slug', () => {
        expect(
            buildLinkCallbackUrl({
                routingMode: 'path',
                publicBaseUrl: 'http://localhost:3030',
                slug: 'weekly-digest',
                provider: 'posthog',
            })
        ).toBe('http://localhost:3030/link/posthog/callback')
    })

    it('path mode trims a trailing slash on the base URL', () => {
        expect(
            buildLinkCallbackUrl({
                routingMode: 'path',
                publicBaseUrl: 'https://x.trycloudflare.com/',
                slug: 'a',
                provider: 'slack',
            })
        ).toBe('https://x.trycloudflare.com/link/slack/callback')
    })

    // Null (rather than a wrong/hardcoded host) is what makes the caller fail the
    // link loudly instead of silently redirecting to the wrong place — the bug
    // this builder replaced.
    it.each([
        ['domain mode without a suffix', { routingMode: 'domain' as const, slug: 's', provider: 'p' }],
        ['path mode without a base URL', { routingMode: 'path' as const, slug: 's', provider: 'p' }],
        [
            'an empty slug in domain mode',
            { routingMode: 'domain' as const, domainSuffix: '.agents.us.posthog.com', slug: '', provider: 'p' },
        ],
    ])('returns null for %s', (_label, opts) => {
        expect(buildLinkCallbackUrl(opts)).toBeNull()
    })
})
