import { cleanedCookieSubdomain } from 'scenes/authentication/redirectToLoggedInInstance'

describe('redirectToLoggedInInstance', () => {
    test.each([
        ['handles null', null, null],
        ['handles the empty string', '', null],
        ['handles the sneaky string', '         ', null],
        ['handles not URLs', 'yo ho ho', null],
        ['handles EU', 'https://eu.posthog.com', 'EU'],
        ['handles US', 'https://app.posthog.com', 'US'],
        ['handles leading quotes', '"https://eu.posthog.com', 'EU'],
        ['handles trailing quotes', 'https://eu.posthog.com"', 'EU'],
        ['handles wrapping quotes', '"https://eu.posthog.com"', 'EU'],
        ['handles ports', 'https://app.posthog.com:8123', 'US'],
        ['handles longer urls', 'https://app.posthog.com:1234?query=parameter#hashParam', 'US'],
    ])('%s', (_name, cookie, expected) => {
        expect(cleanedCookieSubdomain(cookie)).toEqual(expected)
    })
})
