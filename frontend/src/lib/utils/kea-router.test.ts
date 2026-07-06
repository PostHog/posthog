import { addProjectIdIfMissing, decodeParams, stripTrailingSlash } from 'lib/utils/kea-router'

describe('router-utils', () => {
    it('does not redirect account URLs to a project URL', () => {
        const altered = addProjectIdIfMissing('/account/two_factor', 123)
        expect(altered).toEqual('/account/two_factor')
    })
    it('does not allow account urls to have a project url', () => {
        const altered = addProjectIdIfMissing('/project/123/account/two_factor', 123)
        expect(altered).toEqual('/account/two_factor')
    })
    it('allows project urls to use an API key in place of numeric project id', () => {
        const altered = addProjectIdIfMissing('/project/phc_gE7SWBNBgFbA4eQ154KPXebyB8KyLJuypR8jg1DSo9Z/replay', 123)
        expect(altered).toEqual('/project/phc_gE7SWBNBgFbA4eQ154KPXebyB8KyLJuypR8jg1DSo9Z/replay')
    })

    describe('relative path normalization', () => {
        it('normalizes ../ prefix to absolute path with project id', () => {
            expect(addProjectIdIfMissing('../dashboard/1663553', 112509)).toEqual('/project/112509/dashboard/1663553')
        })
        it('normalizes multiple ../ prefixes', () => {
            expect(addProjectIdIfMissing('../../dashboard/1663553', 112509)).toEqual(
                '/project/112509/dashboard/1663553'
            )
        })
        it('normalizes ./ prefix to absolute path with project id', () => {
            expect(addProjectIdIfMissing('./insights/abc123', 112509)).toEqual('/project/112509/insights/abc123')
        })
        it('normalizes repeated ./ prefixes', () => {
            expect(addProjectIdIfMissing('././dashboard/1663553', 112509)).toEqual('/project/112509/dashboard/1663553')
        })
        it('does not alter normal absolute paths', () => {
            expect(addProjectIdIfMissing('/dashboard/1663553', 112509)).toEqual('/project/112509/dashboard/1663553')
        })
    })

    describe('stripTrailingSlash', () => {
        it('strips a single trailing slash', () => {
            expect(stripTrailingSlash('/insights/abc/')).toEqual('/insights/abc')
        })
        it('strips multiple trailing slashes', () => {
            expect(stripTrailingSlash('/insights/abc///')).toEqual('/insights/abc')
        })
        it('preserves the root path', () => {
            expect(stripTrailingSlash('/')).toEqual('/')
        })
        it('leaves paths without trailing slash unchanged', () => {
            expect(stripTrailingSlash('/insights/abc')).toEqual('/insights/abc')
        })
        it('leaves the empty string unchanged', () => {
            expect(stripTrailingSlash('')).toEqual('')
        })
    })

    describe('decodeParams', () => {
        // A dangling `%` in a URL hash (e.g. a truncated pasted link) used to throw URIError
        // from the raw decodeURIComponent in kea-router's default, crashing the app on boot.
        it('does not throw on a dangling percent and keeps the raw value', () => {
            // decodeURIComponent throws on the dangling `%`, so the value degrades to its raw
            // (still percent-encoded) form instead of crashing the app.
            expect(() => decodeParams('#q=%7B%22a%22%3Atrue%', '#')).not.toThrow()
            expect(decodeParams('#q=%7B%22a%22%3Atrue%', '#').q).toEqual('%7B%22a%22%3Atrue%')
        })

        it('still decodes valid params next to a malformed one', () => {
            const params = decodeParams('#a=hello%20world&b=%', '#')
            expect(params.a).toEqual('hello world')
            expect(params.b).toEqual('%')
        })

        it('decodes and coerces well-formed params like the default', () => {
            expect(decodeParams('?n=5&flag=true&s=hello', '?')).toEqual({ n: 5, flag: true, s: 'hello' })
        })
    })
})
