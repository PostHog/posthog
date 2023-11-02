import { cleanedCookieSubdomain } from 'scenes/authentication/redirectToLoggedInInstance'

describe('redirectToLoggedInInstance', () => {
    test.each([
        ['handles null', null, null],
        ['handles EU', 'https://eu.posthog.com', 'eu'],
        ['handles US', 'https://app.posthog.com', 'app'],
        ['handles leading quotes', '"https://eu.posthog.com', 'eu'],
        ['handles trailing quotes', 'https://eu.posthog.com"', 'eu'],
        ['handles wrapping quotes', '"https://eu.posthog.com"', 'eu'],
    ])('%s', (_name, cookie, expected) => {
        expect(cleanedCookieSubdomain(cookie)).toEqual(expected)
    })
})
