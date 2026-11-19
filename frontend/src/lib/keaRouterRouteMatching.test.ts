import { kea, path } from 'kea'
import { router, urlToAction } from 'kea-router'

import { initKeaTests } from '~/test/init'

const matched = jest.fn()

const record =
    (name: string) =>
    (params: Record<string, string | undefined>): void =>
        matched(name, params)

// Order matters: kea-router runs the first route that matches.
const routeMatchingTestLogic = kea([
    path(['lib', 'keaRouterRouteMatching', 'routeMatchingTestLogic']),
    urlToAction(() => ({
        '/things/new': record('thingsNew'),
        '/things/:id': record('thing'),
        '/things/:id/edit': record('thingEdit'),
        '(/:section)/overview': record('optionalLeadingSegment'),
        '/files/*': record('files'),
        '/literal\\:colon': record('escapedColon'),
        '/Case': record('case'),
        '*': record('fallback'),
    })),
])

// Guards kea-router 3.4.2: urlToAction compiles a route pattern only when the path
// starts with the route's static prefix. A wrong prefix would skip a route that should match.
describe('kea-router route matching', () => {
    beforeEach(() => {
        initKeaTests()
        routeMatchingTestLogic.mount()
        matched.mockClear()
    })

    it.each([
        { url: '/things/new', route: 'thingsNew', params: {} },
        { url: '/things/42', route: 'thing', params: { id: '42' } },
        { url: '/things/42/edit', route: 'thingEdit', params: { id: '42' } },
        { url: '/overview', route: 'optionalLeadingSegment', params: {} },
        { url: '/reports/overview', route: 'optionalLeadingSegment', params: { section: 'reports' } },
        { url: '/files/a/b.txt', route: 'files', params: { _: 'a/b.txt' } },
        { url: '/literal:colon', route: 'escapedColon', params: {} },
        { url: '/Case', route: 'case', params: {} },
        { url: '/case', route: 'fallback', params: { _: '/case' } },
        { url: '/thingsnew', route: 'fallback', params: { _: '/thingsnew' } },
    ])('routes $url to $route', ({ url, route, params }) => {
        router.actions.push(url)

        expect(matched).toHaveBeenCalledTimes(1)
        expect(matched).toHaveBeenCalledWith(route, params)
    })
})
