import { defaultAllowLists } from './default-dict'
import { scrubUrl } from './url'

describe('anonymize/url', () => {
    const allow = defaultAllowLists()
    const scrub = (input: string): string => scrubUrl({ allow, maxWordsLen: 8 }, input).value

    it('keeps allow-listed segments and redacts identifiers', () => {
        expect(scrub('https://example.com/api/v1/users/42/profile')).toBe(
            'https://example.com/api/v1/users/[redacted]/profile'
        )
    })

    it('drops query and fragment', () => {
        expect(scrub('https://example.com/dashboard?token=secret#frag')).toBe('https://example.com/dashboard')
    })

    it('redacts segments in a relative path', () => {
        expect(scrub('/user/abc/edit')).toBe('/user/[redacted]/edit')
    })

    it('keeps the authority verbatim for a protocol-relative URL', () => {
        expect(scrub('//cdn.example.com/assets/abc/logo.png')).toBe('//cdn.example.com/assets/[redacted]/[redacted]')
    })

    it('treats a host-only URL (no path) as authority and leaves it unchanged', () => {
        expect(scrub('https://example.com')).toBe('https://example.com')
        expect(scrub('//cdn.example.com')).toBe('//cdn.example.com')
    })

    it('redacts a bare relative segment with no authority', () => {
        expect(scrub('secrettoken')).toBe('[redacted]')
    })

    it('leaves a fully allow-listed path untouched (no change)', () => {
        expect(scrub('https://example.com/api/v1/users')).toBe('https://example.com/api/v1/users')
    })
})
