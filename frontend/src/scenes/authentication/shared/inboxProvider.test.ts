import { inboxProviderLink, parseInboxProvider } from './inboxProvider'

describe('inboxProvider', () => {
    test.each([
        [
            'hog+signup@gmail.com',
            'https://mail.google.com/mail/?authuser=hog%2Bsignup%40gmail.com#search/in%3Aanywhere+newer_than%3A1h',
        ],
        [null, 'https://mail.google.com/mail/#search/in%3Aanywhere+newer_than%3A1h'],
    ])('opens the Gmail account the code went to for %s', (email, url) => {
        expect(inboxProviderLink('gmail', email)).toEqual({ name: 'Gmail', url })
    })

    test.each([
        ['microsoft_365', 'microsoft_365'],
        ['hotmail', null],
        ['constructor', null],
        [undefined, null],
    ])('reads %s from a response as %s', (value, expected) => {
        expect(parseInboxProvider(value)).toBe(expected)
    })
})
