import { AllowLists } from './allow-lists'
import { defaultAllowLists } from './default-dict'
import { scrubUrl } from './url'

describe('anonymize/url', () => {
    const allow = defaultAllowLists()
    const scrub = (input: string): string => scrubUrl({ allow }, input).value

    it('keeps allow-listed segments, masks numbers, and redacts other identifiers', () => {
        expect(scrub('https://example.com/api/v1/users/42/profile')).toBe('https://example.com/api/v1/users/$$/profile')
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

    describe('collapseHost (Meta only)', () => {
        const ctx = { allow: new AllowLists([], ['us', 'api', 'v1', 'users', 'profile']) }
        const sa = (i: string): string => scrubUrl(ctx, i, { collapseHost: true }).value

        it('keeps an allow-listed subdomain and rewrites the rest to example.com', () => {
            expect(sa('https://us.website.com/api/v1/users/42/profile')).toBe(
                'https://us.example.com/api/v1/users/$$/profile'
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
            expect(scrub('https://us.website.com/users/42')).toBe('https://us.website.com/users/$$')
        })
    })

    describe('query and fragment (numbers scrubbed; key/value allow-listed with [key]/[value] fallback)', () => {
        const ctx = { allow: new AllowLists([], ['app', 'page', 'sort', 'tab', 'q', 'about', 'asc', 'settings']) }
        const u = (i: string): string => scrubUrl(ctx, i).value

        it('keeps params whose key and value are both allow-listed (+ an allow-listed fragment)', () => {
            expect(u('https://example.com/app?sort=asc&tab=settings#about')).toBe(
                'https://example.com/app?sort=asc&tab=settings#about'
            )
        })
        it('masks a numeric value with $ per digit, kept because the key is allow-listed', () => {
            expect(u('https://example.com/app?page=2')).toBe('https://example.com/app?page=$')
            expect(u('https://example.com/app?page=2024')).toBe('https://example.com/app?page=$$$$')
        })
        it('drops a param whose only non-denied side is a number (number counts as denied)', () => {
            expect(u('https://example.com/app?id=42')).toBe('https://example.com/app')
        })
        it('replaces the denied side: key allowed + value denied → key=[value]', () => {
            expect(u('https://example.com/app?sort=secret')).toBe('https://example.com/app?sort=[value]')
        })
        it('replaces the denied side: key denied + value allowed → [key]=value', () => {
            expect(u('https://example.com/app?xyz=asc')).toBe('https://example.com/app?[key]=asc')
        })
        it('drops the param only when both key and value are denied', () => {
            expect(u('https://example.com/app?token=secret')).toBe('https://example.com/app')
        })
        it('treats a complex (non-alphanumeric) value as denied → [value]', () => {
            expect(u('https://example.com/app?q=a%20b')).toBe('https://example.com/app?q=[value]')
        })
        it('keeps a bare allow-listed flag and drops a denied one', () => {
            expect(u('https://example.com/app?sort&token')).toBe('https://example.com/app?sort')
        })
        it('keeps an allow-listed fragment and drops a numeric or non-allow-listed one', () => {
            expect(u('https://example.com/app#about')).toBe('https://example.com/app#about')
            expect(u('https://example.com/app#42')).toBe('https://example.com/app') // number alone → dropped
            expect(u('https://example.com/app#xyz')).toBe('https://example.com/app') // not allow-listed
        })
    })

    it('masks a bare-number path segment with $', () => {
        const numCtx = { allow: new AllowLists([], ['users']) }
        expect(scrubUrl(numCtx, 'https://example.com/users/2/x').value).toBe('https://example.com/users/$/[redacted]')
    })
})
