import { installationErrorCopy } from './installationErrorCopy'

describe('installationErrorCopy', () => {
    it.each([
        ['model gate', "Internal error: Failed to authenticate. Model 'claude-sonnet-5' needs a paid PostHog plan"],
        ['org usage limit', 'This organization has reached its PostHog Code usage limit'],
        ['provider terms of service', 'The request is prohibited due to a violation of provider Terms Of Service'],
    ])('maps the %s 403 to copy that names a next step, never the raw string', (_case, rawMessage) => {
        const { title, detail } = installationErrorCopy(rawMessage, false)
        expect(title).not.toBe('Installation failed')
        expect(detail).not.toBe(rawMessage)
        expect(detail).toContain('install PostHog yourself')
    })

    it('gives an unrecognized failure generic copy rather than the raw message', () => {
        const { title, detail } = installationErrorCopy('Segfault at 0xdeadbeef', false)
        expect(title).toBe('Installation failed')
        expect(detail).not.toContain('0xdeadbeef')
        expect(detail).toContain('install PostHog yourself')
    })

    it('has no detail when there is no message', () => {
        expect(installationErrorCopy(null, false)).toEqual({ title: 'Installation failed', detail: null })
    })

    it('keeps a cancel reason verbatim', () => {
        // A cancel is a deliberate stop, never a gateway 403, so its own reason stands.
        expect(installationErrorCopy('Stopped by user', true)).toEqual({
            title: 'Run cancelled',
            detail: 'Stopped by user',
        })
    })
})
