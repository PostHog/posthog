import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { appScenes } from 'scenes/appScenes'
import { prefetchScene, sceneForPathname } from 'scenes/prefetchScene'
import { Scene, SceneTab } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AppContext } from '~/types'

describe('prefetchScene', () => {
    afterEach(() => {
        jest.restoreAllMocks()
        window.history.replaceState(null, '', '/')
    })

    it.each([
        ['a project page', `/project/1${urls.savedInsights()}`, Scene.SavedInsights],
        ['a page with params', `/project/1${urls.replaySingle('abc')}`, Scene.ReplaySingle],
        ['a trailing slash', `/project/1${urls.savedInsights()}/`, Scene.SavedInsights],
        ['a page outside a project', urls.savedInsights(), Scene.SavedInsights],
        ['a redirect to a fixed path', '/project/1/events', Scene.ExploreEvents],
        ['a redirect that builds its path and also matches a route', '/project/1/replay/recent', null],
        ['the root', '/', Scene.ProjectHomepage],
        ['the project root', '/project/1', Scene.ProjectHomepage],
        ['the homepage', '/project/1/home', Scene.ProjectHomepage],
        ['an unknown page', '/project/1/no-such-page/at-all', null],
        ['a path that does not decode', '/project/1/person/50%off', null],
    ])('finds the scene for %s', (_case, pathname, expected) => {
        expect(sceneForPathname(pathname)).toEqual(expected)
    })

    it.each(
        ['/', '/project/1', '/project/1/home'].flatMap((pathname) => [
            [pathname, false, Scene.SavedInsights] as const,
            [pathname, true, Scene.ProjectHomepage] as const,
        ])
    )('finds the scene for %s with a configured homepage (today rail nav: %s)', (pathname, todayRailNav, expected) => {
        jest.spyOn(posthog, 'isFeatureEnabled').mockImplementation(
            (key) => key === FEATURE_FLAGS.TODAY_RAIL_NAV && todayRailNav
        )
        const appContext = window.POSTHOG_APP_CONTEXT
        window.POSTHOG_APP_CONTEXT = {
            ...appContext,
            homepage: { pathname: `/project/1${urls.savedInsights()}`, search: '', hash: '' } as SceneTab,
        } as AppContext
        try {
            expect(sceneForPathname(pathname)).toEqual(expected)
        } finally {
            window.POSTHOG_APP_CONTEXT = appContext
        }
    })

    it.each([
        [
            'throws',
            (): never => {
                throw new Error('import failed')
            },
        ],
        ['rejects', (): Promise<never> => Promise.reject(new Error('import failed'))],
    ])('lets the boot continue when the scene import %s', async (_case, failingImport) => {
        window.history.replaceState(null, '', `/project/1${urls.savedInsights()}`)
        const importScene = jest.spyOn(appScenes, Scene.SavedInsights).mockImplementation(failingImport)

        expect(() => prefetchScene()).not.toThrow()
        await Promise.resolve()

        expect(importScene).toHaveBeenCalledTimes(1)
    })
})
