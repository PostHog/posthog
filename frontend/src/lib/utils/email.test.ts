import { isValidEmail } from './email'

describe('isValidEmail', () => {
    it.each([
        // The regression this replaced: the lowercase-only form rejected a capitalized address.
        ['a capitalized address', 'Foo@Bar.com'],
        ['an all-caps address', 'FOO@BAR.COM'],
        ['a plain address', 'foo@bar.com'],
        ['a subdomain', 'foo@mail.bar.co.uk'],
        ['a plus tag', 'foo+tag@bar.com'],
        // A pasted address keeps the surrounding space the serializers trim off.
        ['a pasted address', '  foo@bar.com  '],
    ])('accepts %s', (_, email) => {
        expect(isValidEmail(email)).toBe(true)
    })

    it.each([
        ['an empty string', ''],
        ['a missing domain', 'foo@'],
        ['a missing local part', '@bar.com'],
        ['a bare word', 'foo'],
        ['a domain with no dot', 'foo@bar'],
        // The unanchored form this replaced accepted anything that merely contained an address.
        ['text around an address', 'my email is foo@bar.com ok'],
        ['a trailing newline', 'foo@bar.com\nrubbish'],
    ])('rejects %s', (_, email) => {
        expect(isValidEmail(email)).toBe(false)
    })
})
