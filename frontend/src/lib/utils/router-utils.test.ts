import { addProjectIdIfMissing, stripTrailingSlash } from 'lib/utils/router-utils'

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
