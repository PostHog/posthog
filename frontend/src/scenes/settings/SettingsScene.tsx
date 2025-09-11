import { useValues } from 'kea'
import { router } from 'kea-router'

import { useAnchor } from 'lib/hooks/useAnchor'
import { SceneExport } from 'scenes/sceneTypes'

import { Settings } from './Settings'
import { settingsSceneLogic } from './settingsSceneLogic'

export const scene: SceneExport = {
    component: SettingsScene,
    logic: settingsSceneLogic,
}

export function SettingsScene(): JSX.Element {
    const { location } = useValues(router)
    useAnchor(location.hash)

    return <Settings logicKey="settingsScene" handleLocally />
}
