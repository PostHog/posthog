import { defaultAllowLists } from './default-dict'
import { scrubText } from './text'

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
})
