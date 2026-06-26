import { AllowLists } from './allow-lists'
import { defaultAllowLists } from './default-dict'
import { scrubUrl } from './url'

describe('anonymize/url', () => {
    const allow = defaultAllowLists()
    const scrub = (input: string): string => scrubUrl({ allow }, input).value

    it('keeps allow-listed segments and redacts identifiers', () => {
        expect(scrub('https://example.com/api/v1/users/42/profile')).toBe(
            'https://example.com/api/v1/users/[redacted]/profile'
        )
    })

    it('drops non-allow-listed query params and fragments', () => {
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

    describe('scrubAuthority (Meta only)', () => {
        const ctx = { allow: new AllowLists([], ['us', 'api', 'v1', 'users', 'profile']) }
        const sa = (i: string): string => scrubUrl(ctx, i, { scrubAuthority: true }).value

        it('keeps an allow-listed subdomain and rewrites the rest to example.com', () => {
            expect(sa('https://us.website.com/api/v1/users/42/profile')).toBe(
                'https://us.example.com/api/v1/users/[redacted]/profile'
            )
        })
        it('drops a 2-label host to example.com (no doubled label)', () => {
            expect(sa('https://website.com/x')).toBe('https://example.com/[redacted]')
            expect(sa('https://example.com/x')).toBe('https://example.com/[redacted]')
        })
        it('strips userinfo and port', () => {
            expect(sa('https://user:pass@us.secret.io:8443/x')).toBe('https://us.example.com/[redacted]')
        })
        it('default (no opts) keeps the authority verbatim', () => {
            expect(scrub('https://us.website.com/users/42')).toBe('https://us.website.com/users/[redacted]')
        })
    })

    describe('query and fragment (allow-listed + alphanumeric only)', () => {
        const ctx = { allow: new AllowLists([], ['app', 'page', 'sort', 'q', 'about']) }
        const q = (i: string): string => scrubUrl(ctx, i).value

        it('keeps allow-listed alphanumeric params and an allow-listed alphanumeric fragment', () => {
            expect(q('https://example.com/app?page=2&sort=asc#about')).toBe(
                'https://example.com/app?page=2&sort=asc#about'
            )
        })
        it('drops a param whose key is not allow-listed', () => {
            expect(q('https://example.com/app?page=2&token=abc')).toBe('https://example.com/app?page=2')
        })
        it('drops a param whose value is not 100% alphanumeric (tokens, encoded, etc.)', () => {
            expect(q('https://example.com/app?q=a%20b&page=2')).toBe('https://example.com/app?page=2')
            expect(q('https://example.com/app?sort=a-b')).toBe('https://example.com/app')
        })
        it('drops a non-allow-listed or non-alphanumeric fragment', () => {
            expect(q('https://example.com/app#xyz')).toBe('https://example.com/app') // not allow-listed
            expect(q('https://example.com/app#ab-1')).toBe('https://example.com/app') // not alphanumeric
        })
    })
})
