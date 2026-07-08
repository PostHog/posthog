import { addProjectIdIfMissing, stripTrailingSlash } from 'lib/utils/kea-router'

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
    it('does not redirect the instance-level feature flags staff tools URL to a project URL', () => {
        const altered = addProjectIdIfMissing('/feature_flags/staff', 123)
        expect(altered).toEqual('/feature_flags/staff')
    })
    it('still adds a project id to other feature flags URLs', () => {
        const altered = addProjectIdIfMissing('/feature_flags/123', 123)
        expect(altered).toEqual('/project/123/feature_flags/123')
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
})
