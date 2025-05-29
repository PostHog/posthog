import { kea, path, props, selectors } from 'kea'
import { ERROR_TRACKING_LOGIC_KEY } from 'scenes/error-tracking/utils'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { errorTrackingAlertSceneLogicType } from './ErrorTrackingAlertType'

export type ErrorTrackingAlertSceneLogicProps = { id: string }

const ERROR_TRACKING_TEMPLATE_IDS = [
    'template-slack-error-tracking-issue-created',
    'template-slack-error-tracking-issue-reopened',
    'template-discord-error-tracking-issue-created',
    'template-discord-error-tracking-issue-reopened',
    'template-microsoft-teams-error-tracking-issue-created',
    'template-microsoft-teams-error-tracking-issue-reopened',
    'template-webhook-error-tracking-issue-created',
    'template-webhook-error-tracking-issue-reopened',
    'template-linear-error-tracking-issue-created',
]

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
    paramsToProps: ({ params: { id } }): (typeof errorTrackingAlertSceneLogic)['props'] => ({ id }),
}

export function ErrorTrackingAlertScene({ id }: Partial<ErrorTrackingAlertSceneLogicProps> = {}): JSX.Element {
    const props = id && ERROR_TRACKING_TEMPLATE_IDS.includes(id) ? { id: null, templateId: id } : { id }
    return (
        <HogFunctionConfiguration
            {...props}
            displayOptions={{ hideTestingConfiguration: false }}
            logicKey={ERROR_TRACKING_LOGIC_KEY}
        />
    )
}
