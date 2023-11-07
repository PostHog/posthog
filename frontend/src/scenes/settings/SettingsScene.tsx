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

/**
 *
 * Settings can be accessed in multiple ways:
 * 1. Via the main settings page - each section is a separate page
 * 2. Via small popups for individual settings
 * 3. Via the sidepanel (3000) for any section
 */

export function SettingsScene(): JSX.Element {
    const { location } = useValues(router)
    useAnchor(location.hash)

    return <Settings logicKey={'settingsScene'} />
}
