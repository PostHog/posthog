import { preloadedScenes } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { lazySceneImports } from '~/lazySceneImports'

export const appScenes = {
    ...lazySceneImports,
    [Scene.Error404]: () => ({ default: preloadedScenes[Scene.Error404].component }),
    [Scene.ErrorNetwork]: () => ({ default: preloadedScenes[Scene.ErrorNetwork].component }),
    [Scene.ErrorProjectUnavailable]: () => ({ default: preloadedScenes[Scene.ErrorProjectUnavailable].component }),
}
