import { cleanedCookieSubdomain } from 'scenes/authentication/RedirectToLoggedInInstance'

describe('RedirectToLoggedInInstance cleanedCookieSubdomain', () => {
    test.each([
        ['handles null', null, null],
        ['handles the empty string', '', null],
        ['handles the sneaky string', '         ', null],
        ['handles not URLs', 'yo ho ho', null],
        ['handles EU', 'https://eu.posthog.com', 'eu'],
        ['handles app', 'https://app.posthog.com', null],
        ['handles US', 'https://us.posthog.com', 'us'],
        ['handles leading quotes', '"https://eu.posthog.com', 'eu'],
        ['handles trailing quotes', 'https://eu.posthog.com"', 'eu'],
        ['handles wrapping quotes', '"https://eu.posthog.com"', 'eu'],
        ['handles ports', 'https://us.posthog.com:8123', 'us'],
        ['handles longer urls', 'https://eu.posthog.com:1234?query=parameter#hashParam', 'eu'],
    ])('%s', (_name, cookie, expected) => {
        expect(cleanedCookieSubdomain(cookie)).toEqual(expected)
    })
})
