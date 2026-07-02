import { defaultAllowLists } from './default-dict'
import { redactEmails, scrubText } from './text'

describe('anonymize/text', () => {
    const allow = defaultAllowLists()
    const scrub = (input: string): string => scrubText({ allow }, input).value

    it('keeps allow-listed words', () => {
        expect(scrub('Click submit to continue')).toBe('Click submit to continue')
    })

    it('redacts unknown words per char', () => {
        expect(scrub('Hello Mr Smithson')).toBe('Hello ** ********')
    })

    it('turns numbers into hash per char', () => {
        expect(scrub('user 42 home 99')).toBe('user ## home ##')
    })

    it('redacts numeric tokens with #', () => {
        expect(scrub('submit 4242 Smithson')).toBe('submit #### ********')
    })

    it('preserves punctuation', () => {
        expect(scrub('user, click submit!')).toBe('user, click submit!')
    })

    it('preserves contractions', () => {
        expect(scrub("I'll click submit but don't save it. Let's continue.")).toBe(
            "I'll click submit but don't save it. Let's continue."
        )
    })

    it('handles the typographic apostrophe', () => {
        expect(scrub('I’ll save it')).toBe('I’ll save it')
    })

    it('lets a possessive inherit its base allow-listing', () => {
        expect(scrub("the user's account")).toBe("the user's account")
    })

    it('keeps allow-listed words in long (>8 word) text — no full-redact threshold', () => {
        expect(scrub('click submit cancel click submit cancel click submit cancel Smithson')).toBe(
            'click submit cancel click submit cancel click submit cancel ********'
        )
    })

    it('preserves code-point length when redacting astral (surrogate-pair) characters', () => {
        // Two CJK-extension-B letters = 2 code points (4 UTF-16 units). Redaction
        // must produce 2 mark chars, not 4.
        expect(scrub('𠀀𠀀')).toBe('**')
    })

    it('redacts whole email addresses via the regex pass (even allow-listed fragments)', () => {
        // `to`/`in` are stop-words the tokenizer would keep, but the email pass nukes the address first.
        expect(scrub('to jane.doe@in.example.com')).toBe('to ' + '*'.repeat('jane.doe@in.example.com'.length))
        expect(scrub('email a@b.co')).not.toContain('a@b.co')
    })

    test.each([
        ['a@.co', 'a@.co'],
        ['a@b.c', 'a@b.c'],
        ['a@b.co', '******'],
        ['user@example.com2', '****************2'],
        ['a@b@c.com', 'a@*******'],
        ['first@a.com second@b.org', '*********** ************'],
        ['user@example.co.uk', '******************'],
        ['trailing@dot.com...', '****************...'],
    ])('redactEmails boundary semantics: %s', (input, expected) => {
        expect(redactEmails(input).value).toBe(expected)
    })

    it('scales linearly on a long unbroken email-charset run (no regex backtracking)', () => {
        // A backtracking email regex is O(n²) here: ~35s at this size vs ~10ms linear.
        const run = 'A1b2C3d4'.repeat((256 * 1024) / 8)
        const start = performance.now()
        scrub(run)
        expect(performance.now() - start).toBeLessThan(5000)
    })
})
