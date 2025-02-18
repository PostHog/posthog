import { kea, path, props, selectors } from 'kea'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
// import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { errorTrackingAlertSceneLogicType } from './ErrorTrackingAlertType'

type ErrorTrackingAlertSceneLogicProps = { id: string }

export const errorTrackingAlertSceneLogic = kea<errorTrackingAlertSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingAlertSceneLogic', key]),
    props({} as ErrorTrackingAlertSceneLogicProps),
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
    paramsToProps: ({ params: { id } }): ErrorTrackingAlertSceneLogicProps => ({ id }),
}

export function ErrorTrackingAlertScene({ id }: ErrorTrackingAlertSceneLogicProps): JSX.Element | null {
    const props = id === 'new' ? { id: null, templateId: 'template-slack-error-tracking-issue-created' } : { id }
    return <HogFunctionConfiguration {...props} />
}
