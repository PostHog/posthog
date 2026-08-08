import { cloudErrorCopy, gatewayErrorCopy } from './installationErrorCopy'

describe('installationErrorCopy', () => {
    it.each([
        ['model gate', "Internal error: Failed to authenticate. Model 'claude-sonnet-5' needs a paid PostHog plan"],
        ['org usage limit', 'This organization has reached its PostHog Code usage limit'],
        ['provider terms of service', 'The request is prohibited due to a violation of provider Terms Of Service'],
    ])('gatewayErrorCopy maps the %s 403 to copy with a next step, never the raw string', (_case, rawMessage) => {
        const mapped = gatewayErrorCopy(rawMessage)
        expect(mapped).not.toBeNull()
        expect(mapped?.detail).not.toBe(rawMessage)
        expect(mapped?.detail).toContain('install PostHog yourself')
    })

    it('gatewayErrorCopy returns null for a message it does not recognize', () => {
        expect(gatewayErrorCopy('Segfault at 0xdeadbeef')).toBeNull()
        expect(gatewayErrorCopy(null)).toBeNull()
    })

    it('cloudErrorCopy gives an unrecognized failure generic copy rather than the raw message', () => {
        const { title, detail } = cloudErrorCopy('Segfault at 0xdeadbeef', false)
        expect(title).toBe('Installation failed')
        expect(detail).not.toContain('0xdeadbeef')
        expect(detail).toContain('install PostHog yourself')
    })

    it('cloudErrorCopy has no detail when there is no message', () => {
        expect(cloudErrorCopy(null, false)).toEqual({ title: 'Installation failed', detail: null })
    })

    it('cloudErrorCopy keeps a cancel reason verbatim', () => {
        // A cancel is a deliberate stop, never a gateway 403, so its own reason stands.
        expect(cloudErrorCopy('Stopped by user', true)).toEqual({ title: 'Run cancelled', detail: 'Stopped by user' })
    })
})
