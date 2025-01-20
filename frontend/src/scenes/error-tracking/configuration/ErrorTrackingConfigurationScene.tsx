import { SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'

import { AlphaAccessScenePrompt } from '../AlphaAccessScenePrompt'

export const scene: SceneExport = {
    component: ErrorTrackingConfigurationScene,
}

export function ErrorTrackingConfigurationScene(): JSX.Element {
    return (
        <AlphaAccessScenePrompt>
            <Settings
                logicKey="errorTracking"
                sectionId="environment-error-tracking"
                settingId="error-tracking-user-groups"
                handleLocally
            />
        </AlphaAccessScenePrompt>
    )
}
