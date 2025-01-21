import { kea, path, props, selectors } from 'kea'
// import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { errorTrackingAlertSceneLogicType } from './ErrorTrackingAlertType'

export const errorTrackingAlertSceneLogic = kea<errorTrackingAlertSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingAlertSceneLogic', key]),
    props({} as { id: string }),
    selectors({
        breadcrumbs: [
            (_, p) => [p.id],
            (id): Breadcrumb[] => [
                {
                    key: Scene.ErrorTracking,
                    path: urls.errorTracking(),
                    name: 'Error tracking',
                },
                {
                    key: Scene.ErrorTrackingConfiguration,
                    path: urls.errorTrackingConfiguration(),
                    name: 'Alerts',
                },
                {
                    key: Scene.ErrorTrackingAlert,
                    name: id === 'new' ? 'Create alert' : 'Edit alert',
                },
            ],
        ],
    }),
])

export const scene: SceneExport = {
    component: ErrorTrackingAlertScene,
    logic: errorTrackingAlertSceneLogic,
    paramsToProps: ({ params: { id } }): (typeof errorTrackingAlertSceneLogic)['props'] => ({ id }),
}

export function ErrorTrackingAlertScene(): JSX.Element | null {
    return null
    // return <HogFunctionConfiguration id={null} templateId="template-error-tracking-alert" />
}
