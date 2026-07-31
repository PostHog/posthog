import { isTrustedPostHogUrl } from './trustedUrl'

describe('isTrustedPostHogUrl', () => {
    // jsdom serves tests from http://localhost, so same-origin checks resolve against localhost.
    it.each([
        ['/static/screenshot.png'],
        ['http://localhost/img.png'],
        ['https://posthog.com/img.png'],
        ['https://us.posthog.com/img.png'],
        ['https://app.posthog.com/a/b/c.png'],
    ])('trusts %s', (url) => {
        expect(isTrustedPostHogUrl(url)).toBe(true)
    })

    it.each([
        ['https://evil.com/img.png'],
        ['https://notposthog.com/img.png'],
        ['https://evil.posthog.com.attacker.com/img.png'],
        ['https://posthog.com.attacker.com/img.png'],
        ['data:image/png;base64,iVBORw0KGgo='],
        ['blob:https://posthog.com/abc'],
        ['javascript:alert(1)'],
        [''],
        [undefined],
    ])('distrusts %s', (url) => {
        expect(isTrustedPostHogUrl(url)).toBe(false)
    })
})
