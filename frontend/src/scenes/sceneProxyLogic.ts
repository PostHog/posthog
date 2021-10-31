import { Scene } from 'scenes/sceneTypes'
import { kea } from 'kea'
import { sceneProxyLogicType } from './sceneProxyLogicType'

export const sceneSelector = (state: any): Scene | null => state?.scenes?.sceneLogic?.scene || null
export const sceneProxyLogic = kea<sceneProxyLogicType>({
    selectors: {
        scene: [() => [sceneSelector], (scene) => scene],
    },
})
