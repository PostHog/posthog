import { kea, path, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { sdkDoctorSceneLogicType } from './sdkDoctorSceneLogicType'

export const sdkDoctorSceneLogic = kea<sdkDoctorSceneLogicType>([
    path(['scenes', 'onboarding', 'sdks', 'sdkDoctorSceneLogic']),
    tabAwareScene(),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Health,
                    name: sceneConfigurations[Scene.Health].name,
                    path: urls.health(),
                },
                {
                    key: Scene.SdkDoctor,
                    name: sceneConfigurations[Scene.SdkDoctor].name,
                    iconType: sceneConfigurations[Scene.SdkDoctor].iconType || 'default_icon_type',
                },
            ],
        ],
    }),
])
