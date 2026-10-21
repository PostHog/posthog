import path from 'node:path'

import { preloadedScenes, sceneConfigurations } from 'scenes/scenes'

import { LOGGED_OUT_SCENES, sceneModules } from './loggedOutScenes.mjs'

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
})
