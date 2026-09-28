import { router } from 'kea-router'

import { initKea } from '~/initKea'

import { createEmbedRouterBinding, syncRouterFromHost } from './embedRouter'
import type { EmbedHost, EmbedLocation } from './embedTypes'

function createHost(initial: string): { host: EmbedHost; navigate: jest.Mock; setLocation: (url: string) => void } {
    let location: EmbedLocation = parse(initial)
    const navigate = jest.fn((url: string) => {
        location = parse(url)
    })
    const host: EmbedHost = {
        backendHost: 'https://us.posthog.com',
        getAccessToken: () => 'token',
        refreshAccessToken: async () => 'token',
        getLocation: () => location,
        navigate,
        signOut: jest.fn(),
        theme: 'light',
    }
    return { host, navigate, setLocation: (url) => (location = parse(url)) }
}

function parse(url: string): EmbedLocation {
    const parsed = new URL(url, 'https://embed.example.com')
    return { pathname: parsed.pathname, search: parsed.search, hash: parsed.hash }
}

describe('embedRouter', () => {
    it('routes app navigation through the host and picks up host navigation once', () => {
        const { host, navigate, setLocation } = createHost('/project/1/insights')
        const { history, location } = createEmbedRouterBinding(host)
        initKea({ routerHistory: history, routerLocation: location, replaceInitialPathInWindow: false })
        const windowPath = window.location.pathname

        expect(router.values.location.pathname).toBe('/project/1/insights')

        router.actions.push('/project/1/dashboard')
        expect(navigate).toHaveBeenCalledWith('/project/1/dashboard', { replace: false })
        expect(window.location.pathname).toBe(windowPath)

        const locationChanged = jest.spyOn(router.actions, 'locationChanged')
        syncRouterFromHost(host)
        expect(locationChanged).not.toHaveBeenCalled()

        setLocation('/project/1/feature_flags?tab=overview')
        syncRouterFromHost(host)
        expect(router.values.location.pathname).toBe('/project/1/feature_flags')
        expect(router.values.searchParams).toEqual({ tab: 'overview' })
    })
})
