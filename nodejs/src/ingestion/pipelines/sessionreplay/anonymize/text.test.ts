import { defaultAllowLists } from './default-dict'
import { scrubText } from './text'

describe('anonymize/text', () => {
    const allow = defaultAllowLists()
    const scrub = (input: string, maxWordsLen = 8): string => scrubText({ allow, maxWordsLen }, input).value

    it('keeps allow-listed words', () => {
        expect(scrub('Click submit to continue')).toBe('Click submit to continue')
    })

    it('redacts unknown words per char', () => {
        expect(scrub('Hello Mr Smithson')).toBe('Hello ** ********')
    })

    it('turns numbers into hash per char', () => {
        expect(scrub('user 42 home 99')).toBe('user ## home ##')
    })

    it('redacts numbers even in force-redact-all mode', () => {
        expect(scrub('click submit 42 today', 2)).toBe('***** ****** ## *****')
    })

    it('preserves punctuation', () => {
        expect(scrub('user, click submit!')).toBe('user, click submit!')
    })

    it('preserves contractions', () => {
        expect(scrub("I'll click submit but don't save it. Let's continue.", 100)).toBe(
            "I'll click submit but don't save it. Let's continue."
        )
    })

    it('handles the typographic apostrophe', () => {
        expect(scrub('I’ll save it')).toBe('I’ll save it')
    })

    it('lets a possessive inherit its base allow-listing', () => {
        expect(scrub("the user's account")).toBe("the user's account")
    })

    it('force-redacts when there are too many words', () => {
        expect(scrub('click submit save cancel', 3)).toBe('***** ****** **** ******')
    })

    it('allows allow-listed words under the word-count threshold', () => {
        expect(scrub('click submit cancel', 5)).toBe('click submit cancel')
    })

    it('preserves code-point length when redacting astral (surrogate-pair) characters', () => {
        // Two CJK-extension-B letters = 2 code points (4 UTF-16 units). Redaction
        // must produce 2 mark chars, not 4.
        expect(scrub('𠀀𠀀')).toBe('**')
    })
})
