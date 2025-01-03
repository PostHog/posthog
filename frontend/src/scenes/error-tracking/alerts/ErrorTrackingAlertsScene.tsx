import { LemonButton } from '@posthog/lemon-ui'
import { kea, path, selectors } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'
import { SceneExport } from 'scenes/sceneTypes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { errorTrackingAlertsSceneLogicType } from './ErrorTrackingAlertsSceneType'

export const errorTrackingAlertsSceneLogic = kea<errorTrackingAlertsSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingAlertsSceneLogic']),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.ErrorTracking,
                    name: 'Error tracking',
                    path: urls.errorTracking(),
                },
                {
                    key: Scene.ErrorTrackingAlerts,
                    name: 'Alerts',
                },
            ],
        ],
    }),
])

export const scene: SceneExport = {
    component: ErrorTrackingAlertsScene,
    logic: errorTrackingAlertsSceneLogic,
}

export function ErrorTrackingAlertsScene(): JSX.Element {
    return (
        <>
            <PageHeader
                buttons={
                    <LemonButton type="primary" to={urls.errorTrackingAlert('new')} className="flex">
                        Setup alert
                    </LemonButton>
                }
            />

            <LinkedHogFunctions
                logicKey="error-tracking-alerts"
                type="internal_destination"
                subTemplateId="errors"
                filters={{
                    events: [
                        {
                            id: `$error_something`,
                            type: 'events',
                        },
                    ],
                }}
            />
            {/* <DestinationsTable types={['error_tracking_alert']} hideKind hideFeedback /> */}
        </>
    )
}
