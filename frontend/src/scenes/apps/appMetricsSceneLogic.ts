import { kea, key, props, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { appMetricsSceneLogicType } from './appMetricsSceneLogicType'
import { urls } from 'scenes/urls'
import { Breadcrumb, PluginConfigWithPluginInfo } from '~/types'
import api from '../../lib/api'
import { teamLogic } from '../teamLogic'
import { urlToAction } from 'kea-router'

export interface AppMetricsLogicProps {
    /** Used as the logic's key */
    pluginConfigId: number
}

export const appMetricsSceneLogic = kea<appMetricsSceneLogicType>([
    path(['scenes', 'apps', 'appMetricsSceneLogic']),
    props({} as AppMetricsLogicProps),
    key((props) => props.pluginConfigId),

    loaders(({ props }) => ({
        pluginConfig: [
            null as PluginConfigWithPluginInfo | null,
            {
                loadPluginConfig: async () => {
                    return await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/plugin_configs/${props.pluginConfigId}`
                    )
                },
            },
        ],
    })),

    selectors(() => ({
        breadcrumbs: [
            (s) => [s.pluginConfig, (_, props) => props.pluginConfigId],
            (pluginConfig, pluginConfigId: number): Breadcrumb[] => [
                {
                    name: 'Apps',
                    path: urls.projectApps(),
                },
                {
                    name: pluginConfig?.plugin_info?.name,
                    path: urls.appMetrics(pluginConfigId),
                },
            ],
        ],
    })),

    urlToAction(({ actions }) => ({
        '/app/:pluginConfigId/metrics': () => {
            actions.loadPluginConfig()
        },
    })),
])
