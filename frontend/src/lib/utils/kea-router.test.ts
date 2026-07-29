import {
    addProjectIdIfMissing,
    ensureRoutablePathname,
    getProjectSwitchTargetUrl,
    stripTrailingSlash,
} from 'lib/utils/kea-router'

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
    it('does not redirect the staff tools URL when it carries a query string', () => {
        const altered = addProjectIdIfMissing('/feature_flags/staff?team_id=456', 123)
        expect(altered).toEqual('/feature_flags/staff?team_id=456')
    })
    it('does not redirect the staff tools URL when it carries a hash', () => {
        const altered = addProjectIdIfMissing('/feature_flags/staff#cache', 123)
        expect(altered).toEqual('/feature_flags/staff#cache')
    })
    it('still adds a project id to other feature flags URLs', () => {
        const altered = addProjectIdIfMissing('/feature_flags/123', 123)
        expect(altered).toEqual('/project/123/feature_flags/123')
    })
    it('does not redirect the cohorts staff tools URL nested under feature flags staff', () => {
        const altered = addProjectIdIfMissing('/feature_flags/staff/cohorts', 123)
        expect(altered).toEqual('/feature_flags/staff/cohorts')
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

    describe('ensureRoutablePathname', () => {
        // kea-router runs decodeURI(pathname) while matching; a stray `%` used to throw URIError
        // and crash routing before any scene loaded. Whatever we return must be decodeURI-safe.
        it.each([
            ['/person/50%off', '/person/50%25off'], // lone `%` gets escaped
            ['/person/foo%', '/person/foo%25'], // trailing `%` gets escaped
            ['/person/50%25off', '/person/50%25off'], // already-valid escape is untouched
            ['/person/foo bar', '/person/foo bar'], // whitespace decodes fine, left alone
            ['/insights/abc', '/insights/abc'], // plain path untouched
        ])('makes %s routable as %s', (input, expected) => {
            const result = ensureRoutablePathname(input)
            expect(result).toEqual(expected)
            expect(() => decodeURI(result)).not.toThrow()
        })
    })

    describe('getProjectSwitchTargetUrl', () => {
        // Org-, instance- and user-level paths used to get a `/project/<id>` prefix they can't
        // have (e.g. `/project/2/organization`), which has no route and rendered NotFound.
        it.each([
            ['/organization/billing/overview'],
            ['/organization/billing'],
            ['/instance/status'],
            ['/me/settings'],
            ['/account/two_factor'],
        ])('sends %s to the new project root', (path) => {
            expect(getProjectSwitchTargetUrl(path, 2, 1, 5)).toEqual('/project/2')
            // Same project, different team — the other branch of the helper, broken the same way
            expect(getProjectSwitchTargetUrl(path, 2, 1, 1)).toEqual('/project/2')
        })

        it.each([
            ['/insights/abc123', 1, 5, '/project/2/insights'],
            ['/insights/abc123', 1, 1, '/project/2/insights/abc123'],
            ['/settings/organization', 1, 5, '/project/2/settings/organization'],
            ['/onboarding/product-analytics', 1, 5, '/project/2'],
        ])('keeps project-level %s working', (path, currentProjectId, newProjectId, expected) => {
            expect(getProjectSwitchTargetUrl(path, 2, currentProjectId, newProjectId)).toEqual(expected)
        })
    })
})
