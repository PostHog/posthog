import { kea, key, props, path, selectors } from 'kea'

import type { appMetricsSceneLogicType } from './appMetricsSceneLogicType'
import { urls } from 'scenes/urls'
import { Breadcrumb } from '~/types'

export interface AppMetricsLogicProps {
    /** Used as the logic's key */
    pluginConfigId: number
}

export const appMetricsSceneLogic = kea<appMetricsSceneLogicType>([
    path(['scenes', 'apps', 'appMetricsSceneLogic']),
    props({} as AppMetricsLogicProps),
    key((props) => props.pluginConfigId),

    selectors({
        breadcrumbs: [
            () => [(_, props) => props.pluginConfigId],
            (pluginConfigId: number): Breadcrumb[] => [
                {
                    name: 'Apps',
                    path: urls.projectApps(),
                },
                {
                    // :TODO: Load and show plugin name here
                    name: `Metrics for ${pluginConfigId}`,
                    path: urls.appMetrics(pluginConfigId),
                },
            ],
        ],
    }),
])
