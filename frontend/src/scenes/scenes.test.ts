import { redirects } from 'scenes/scenes'

describe('scenes redirects', () => {
    // The kea router strips `/project/<id>` before matching against the redirects table, so
    // these keys correspond to the real navigation surfaces seen in `not_found_shown` events
    // — `/organization`, `/project/<id>/products`, `/organization/projects`, etc. Without
    // these entries, the wildcard `/*` route in sceneLogic loads Scene.Error404 and the user
    // lands on a dead end.
    it.each([
        ['/project'],
        ['/organization'],
        ['/organization/projects'],
        ['/organization/members'],
        ['/organization/settings'],
        ['/products'],
    ])('has a redirect entry for %s so it does not 404', (path) => {
        expect(redirects[path]).not.toBeUndefined()
    })
})
