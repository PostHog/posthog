import { addProjectIdIfMissing, getProjectSwitchTargetUrl, stripTrailingSlash } from 'lib/utils/kea-router'

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

    describe('getProjectSwitchTargetUrl', () => {
        const CURRENT_TEAM = 111
        const NEW_TEAM = 222

        it('falls back to the new project home from an org-level page (would 404 as bare /organization)', () => {
            // /organization/* has no project prefix; mapping it onto a project gets stripped back to
            // a routeless bare path by locationChanged, landing on "Page not found".
            expect(getProjectSwitchTargetUrl('/organization/billing', NEW_TEAM)).toEqual(`/project/${NEW_TEAM}`)
        })

        it.each([
            ['/instance/status', `/project/${NEW_TEAM}`],
            ['/account/two_factor', `/project/${NEW_TEAM}`],
            ['/organization/members', `/project/${NEW_TEAM}`],
        ])('sends project-less path %s to the new project home', (path, expected) => {
            expect(getProjectSwitchTargetUrl(path, NEW_TEAM)).toEqual(expected)
        })

        it.each([
            ['/project/111/replay-vision', `/project/${NEW_TEAM}`],
            ['/project/111/replay-vision/018f-scanner-uuid', `/project/${NEW_TEAM}`],
        ])(
            'sends beta flag-gated product route %s to the new project home (flag may be off there)',
            (path, expected) => {
                expect(getProjectSwitchTargetUrl(path, NEW_TEAM)).toEqual(expected)
            }
        )

        it('does not keep a stale beta resource id even within the same project', () => {
            expect(getProjectSwitchTargetUrl('/project/111/replay-vision/018f-scanner-uuid', NEW_TEAM, 5, 5)).toEqual(
                `/project/${NEW_TEAM}`
            )
        })

        it('keeps settings routes on the same page in the new project', () => {
            expect(getProjectSwitchTargetUrl('/project/111/settings/project', NEW_TEAM)).toEqual(
                `/project/${NEW_TEAM}/settings/project`
            )
        })

        it('redirects products/onboarding to the new project home', () => {
            expect(getProjectSwitchTargetUrl('/project/111/products', NEW_TEAM)).toEqual(`/project/${NEW_TEAM}`)
        })

        it('drops a resource id when switching across projects', () => {
            expect(getProjectSwitchTargetUrl('/project/111/insights/abc123', NEW_TEAM, 1, 2)).toEqual(
                `/project/${NEW_TEAM}/insights`
            )
        })

        it('keeps a resource id when switching between teams in the same project', () => {
            expect(getProjectSwitchTargetUrl('/project/111/insights/abc123', NEW_TEAM, 7, 7)).toEqual(
                `/project/${NEW_TEAM}/insights/abc123`
            )
        })

        it('keeps a top-level product route across projects', () => {
            expect(getProjectSwitchTargetUrl(`/project/${CURRENT_TEAM}/dashboard`, NEW_TEAM)).toEqual(
                `/project/${NEW_TEAM}/dashboard`
            )
        })
    })
})
