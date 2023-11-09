import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { settingsSceneLogic } from './settingsSceneLogic'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { Settings } from './Settings'

export const scene: SceneExport = {
    component: SettingsScene,
    logic: settingsSceneLogic,
}

export function SettingsScene(): JSX.Element {
    const { location } = useValues(router)
    useAnchor(location.hash)

    return <Settings logicKey={'settingsScene'} />
}
