import { cleanedCookieSubdomain } from 'scenes/authentication/redirectToLoggedInInstance'

describe('redirectToLoggedInInstance', () => {
    test.each([
        ['handles null', null, null],
        ['handles the empty string', '', null],
        ['handles the sneaky string', '         ', null],
        ['handles not URLs', 'yo ho ho', null],
        ['handles EU', 'https://eu.posthog.com', 'eu'],
        ['handles US', 'https://app.posthog.com', 'app'],
        ['handles leading quotes', '"https://eu.posthog.com', 'eu'],
        ['handles trailing quotes', 'https://eu.posthog.com"', 'eu'],
        ['handles wrapping quotes', '"https://eu.posthog.com"', 'eu'],
        ['handles ports', 'https://app.posthog.com:8123', 'app'],
        ['handles longer urls', 'https://app.posthog.com:1234?query=parameter#hashParam', 'app'],
    ])('%s', (_name, cookie, expected) => {
        expect(cleanedCookieSubdomain(cookie)).toEqual(expected)
    })
})
