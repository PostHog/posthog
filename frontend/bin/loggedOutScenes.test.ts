import path from 'node:path'

import { preloadedScenes, sceneConfigurations } from 'scenes/scenes'

import { LOGGED_OUT_SCENES, sceneLoaders, sceneModules } from './loggedOutScenes.mjs'

describe('LOGGED_OUT_SCENES', () => {
    // A logged-out scene missing from the list has no import map entries for its chunks on the stable
    // chunk build, so its page reloads on the hashed build every time.
    it('lists every scene with a loader that a logged-out page can show', () => {
        const scenesWithLoaders = sceneModules(path.resolve(__dirname, '..'))
        const loggedOutScenes = Object.entries(sceneConfigurations)
            .filter(([, config]) => config.onlyUnauthenticated || config.allowUnauthenticated)
            .map(([scene]) => scene)
            .filter((scene) => !(scene in preloadedScenes))

        expect([...LOGGED_OUT_SCENES].sort()).toEqual(loggedOutScenes.sort())
        expect(LOGGED_OUT_SCENES.filter((scene) => !scenesWithLoaders.has(scene))).toEqual([])
    })

    // The build regenerates productScenes.tsx, and the formatter's quote style depends on which config it finds.
    it.each([
        ['single quotes', `{ Heatmaps: () => import('./HeatmapsScene'), [Scene.Login]: () => import('./Login') }`],
        ['double quotes', `{ Heatmaps: () => import("./HeatmapsScene"), [Scene.Login]: () => import("./Login") }`],
        ['quoted keys', `{ "Heatmaps": () => import("./HeatmapsScene"), [Scene.Login]: () =>\n import("./Login") }`],
    ])('reads scene loaders written with %s', (_, source) => {
        expect(sceneLoaders(source, 'registry.ts')).toEqual([
            ['Heatmaps', './HeatmapsScene'],
            ['Login', './Login'],
        ])
    })

    it('fails on a loader it cannot read', () => {
        expect(() => sceneLoaders('{ Heatmaps: () => import(`./HeatmapsScene`) }', 'registry.ts')).toThrow(
            'registry.ts'
        )
    })
})
