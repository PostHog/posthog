import { urlPatternWarning } from './urlConfigLogic'

describe('urlConfigLogic', () => {
    describe('urlPatternWarning', () => {
        // The privacy footgun: patterns are saved anchored as `^...$` and matched against the full
        // window.location.href, so a bare path fragment silently never matches. These cases guard the
        // warning that steers users away from that, without false-warning on real full-URL regexes.
        it.each<[string, 'warns' | 'ok']>([
            // bare path fragments that anchor to something that can never match a full URL
            ['admin-panel', 'warns'],
            ['/admin-panel', 'warns'],
            ['/settings/account', 'warns'],
            ['example.com/admin', 'warns'],
            // grouped/alternation path fragments anchor to e.g. ^(admin|billing)$, still unmatchable
            ['(admin|billing)', 'warns'],
            ['(?:admin|billing)', 'warns'],
            ['(/admin|/billing)', 'warns'],
            // patterns that can match a full URL from the start
            ['.*admin-panel.*', 'ok'],
            ['^https://site.com/admin-panel$', 'ok'],
            ['https://app.posthog.com/.*', 'ok'],
            ['(?:https?://).*/admin', 'ok'],
            // empty / whitespace never warns
            ['', 'ok'],
            ['   ', 'ok'],
        ])('%s -> %s', (input, expected) => {
            const result = urlPatternWarning(input)
            if (expected === 'warns') {
                expect(result).not.toBeNull()
            } else {
                expect(result).toBeNull()
            }
        })

        it('nudges a bare domain towards the path-matching form', () => {
            expect(urlPatternWarning('https://example.com')).toContain('(/.*)?')
        })
    })
})
