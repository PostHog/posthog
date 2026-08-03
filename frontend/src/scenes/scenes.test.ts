import { redirects } from 'scenes/scenes'
import { urls } from 'scenes/urls'

describe('scenes', () => {
    it('redirects the index-less /groups path to the first group type instead of 404ing', () => {
        const redirect = redirects['/groups']
        const target = typeof redirect === 'function' ? redirect({}, {}, {}) : redirect
        expect(target).toEqual(urls.groups(0))
    })
})
