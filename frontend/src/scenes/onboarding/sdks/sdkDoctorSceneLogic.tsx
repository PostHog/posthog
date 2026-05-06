import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { sdkDoctorSceneLogicType } from './sdkDoctorSceneLogicType'

export const sdkDoctorSceneLogic = kea<sdkDoctorSceneLogicType>([
    path(['scenes', 'onboarding', 'sdks', 'sdkDoctorSceneLogic']),
    tabAwareScene(),
    actions({
        setAlertsModalOpen: (open: boolean) => ({ open }),
        openAlertsModal: true,
    }),
    reducers({
        alertsModalOpen: [
            false,
            {
                setAlertsModalOpen: (_, { open }) => open,
            },
        ],
    }),
    listeners(({ actions }) => ({
        openAlertsModal: () => {
            posthog.capture('sdk doctor alerts modal opened')
            actions.setAlertsModalOpen(true)
        },
    })),
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
