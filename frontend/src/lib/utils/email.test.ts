import { isValidEmail } from './email'

// Every case below was run against Django 5.2.17's own `validate_email`, the validator
// `serializers.EmailField` uses, and the verdicts match. The only deliberate difference is the
// bracketed IP literal, where this over-accepts a malformed address rather than blocking a
// submit the server would have taken.
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
        // Dotless, and the one bracketed form, which only Django's allowlist and literal form take.
        ['the local machine', 'user@localhost'],
        ['an IP literal', 'user@[127.0.0.1]'],
        // A quoted local part, and a punycode label.
        ['a quoted local part holding an @', '"test@test"@example.com'],
        ['a punycode domain', 'foo@xn--80ak6aa92e.com'],
        ['a punycode TLD', 'foo@bar.xn--p1ai'],
        ['a 63-character label', `foo@${'a'.repeat(63)}.com`],
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
        // Limits Django applies that a naive regex does not, so these used to reach the server.
        ['a one-character TLD', 'foo@bar.c'],
        ['a numeric TLD', 'foo@bar.1'],
        ['a 64-character label', `foo@${'a'.repeat(64)}.com`],
        ['an address over 320 characters', `${'x'.repeat(320)}@bar.com`],
        // A dash may not start or end any label.
        ['a leading dash in the domain', 'foo@-bar.com'],
        ['a trailing dash in the domain', 'foo@bar-.com'],
        ['an empty label', 'foo@bar..com'],
        ['a trailing dot', 'foo@bar.com.'],
        ['a space in an unquoted local part', 'foo bar@baz.com'],
        // Django's quoted-string range stops short of the space, so quoting one does not help.
        ['a space in a quoted local part', '"foo bar"@baz.com'],
        ['a leading dot in the local part', '.foo@bar.com'],
        ['a bare IP domain', 'foo@127.0.0.1'],
    ])('rejects %s', (_, email) => {
        expect(isValidEmail(email)).toBe(false)
    })
})
