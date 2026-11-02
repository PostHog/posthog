import { appScenes } from 'scenes/appScenes'
import { prefetchScene, sceneForPathname } from 'scenes/prefetchScene'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

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
        ['a redirect that also matches a route', '/project/1/replay/recent', null],
        ['the root', '/', null],
        ['an unknown page', '/project/1/no-such-page/at-all', null],
        ['a path that does not decode', '/project/1/person/50%off', null],
    ])('finds the scene for %s', (_case, pathname, expected) => {
        expect(sceneForPathname(pathname)).toEqual(expected)
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
