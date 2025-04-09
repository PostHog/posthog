import { kea, path, props, selectors } from 'kea'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { HogFunctionConfiguration } from '~/scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { Breadcrumb } from '~/types'

import type { insightAlertDestinationSceneLogicType } from './InsightAlertDestinationSceneType'

export type InsightAlertDestinationSceneLogicProps = { id?: string }

export const insightAlertDestinationSceneLogic = kea<insightAlertDestinationSceneLogicType>([
    path((key) => ['scenes', 'insights', 'insightAlertDestinationSceneLogic', key]),
    props({} as InsightAlertDestinationSceneLogicProps),
    selectors({
        breadcrumbs: [
            (_, p) => [p.id],
            (id): Breadcrumb[] => [
                {
                    key: Scene.Insight,
                    path: urls.insights(),
                    name: 'Insights',
                },
                {
                    key: Scene.InsightAlertDestination,
                    name: id === 'new' ? 'Create alert destination' : 'Edit alert destination',
                },
            ],
        ],
    }),
])

export const scene: SceneExport = {
    component: InsightAlertDestinationScene,
    logic: insightAlertDestinationSceneLogic,
    paramsToProps: ({ params }): InsightAlertDestinationSceneLogicProps => ({ id: params.id }),
}

const INSIGHT_ALERT_FIRING_TEMPLATE_ID = 'hog-template-slack-insight-alert-firing'

export const INSIGHT_ALERT_DESTINATION_LOGIC_KEY = 'insightAlertDestination'

export function InsightAlertDestinationScene({ id }: InsightAlertDestinationSceneLogicProps = {}): JSX.Element {
    const configProps = id && id === INSIGHT_ALERT_FIRING_TEMPLATE_ID ? { id: null, templateId: id } : { id }

    return (
        <HogFunctionConfiguration
            {...configProps}
            logicKey={INSIGHT_ALERT_DESTINATION_LOGIC_KEY}
            displayOptions={{ hideTestingConfiguration: true }}
        />
    )
}
