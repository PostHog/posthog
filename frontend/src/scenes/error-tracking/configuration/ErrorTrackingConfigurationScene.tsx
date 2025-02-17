import { kea, path, selectors } from 'kea'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { AlphaAccessScenePrompt } from '../AlphaAccessScenePrompt'
import type { errorTrackingConfigurationSceneLogicType } from './ErrorTrackingConfigurationSceneType'

export const errorTrackingConfigurationSceneLogic = kea<errorTrackingConfigurationSceneLogicType>([
    path(['scenes', 'error-tracking', 'configuration', 'errorTrackingConfigurationSceneLogic']),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.ErrorTracking,
                    path: urls.errorTracking(),
                    name: 'Error tracking',
                },
                {
                    key: Scene.ErrorTrackingConfiguration,
                    path: urls.errorTrackingConfiguration(),
                    name: 'Configuration',
                },
            ],
        ],
    }),
])

export const scene: SceneExport = {
    component: ErrorTrackingConfigurationScene,
    logic: errorTrackingConfigurationSceneLogic,
}

export function ErrorTrackingConfigurationScene(): JSX.Element {
    return (
        <AlphaAccessScenePrompt>
            <Settings
                logicKey="errorTracking"
                sectionId="environment-error-tracking"
                settingId="error-tracking-user-groups" // acts as a default
                handleLocally
            />
        </AlphaAccessScenePrompt>
    )
}
