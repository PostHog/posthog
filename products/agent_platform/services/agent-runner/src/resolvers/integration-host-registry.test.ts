import { INTEGRATION_HOST_REGISTRY, makeIntegrationHostValidator } from './integration-host-registry'

describe('makeIntegrationHostValidator', () => {
    const validate = makeIntegrationHostValidator(INTEGRATION_HOST_REGISTRY)

    it.each([
        { label: 'slack REST root', host: 'slack.com' },
        { label: 'slack api subdomain', host: 'api.slack.com' },
        { label: 'slack mcp subdomain', host: 'mcp.slack.com' },
    ])('allows the slack integration against $label', ({ host }) => {
        expect(validate('slack:T01XXX', new URL(`https://${host}/api/chat.postMessage`))).toBe(true)
    })

    it.each([
        { label: 'arbitrary public host', host: 'evil.com' },
        { label: 'host that *contains* a known TLD', host: 'slack.com.evil.com' },
        { label: 'lookalike host', host: 'sl4ck.com' },
        { label: 'wrong subdomain', host: 'wrong.slack.com' },
    ])('rejects the slack integration against $label', ({ host }) => {
        expect(validate('slack:T01XXX', new URL(`https://${host}/anything`))).toBe(false)
    })

    it('rejects unknown integration kinds (fail-closed)', () => {
        expect(validate('linear:abc', new URL('https://mcp.linear.app/'))).toBe(false)
    })

    it.each([
        { label: 'no colon', ref: 'slack' },
        { label: 'empty kind', ref: ':T01XXX' },
        { label: 'empty string', ref: '' },
    ])('rejects malformed integration refs ($label)', ({ ref }) => {
        expect(validate(ref, new URL('https://slack.com/'))).toBe(false)
    })
})
