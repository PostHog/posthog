import { connect, kea, path, selectors } from 'kea'

import { ProductKey } from '~/types'

import type { pipelineDefaultEnabledLogicType } from './pipelineDefaultEnabledLogicType'
import { pipelineTransformationsLogic } from './transformationsLogic'

interface PluginContent {
    title: string
    description: string
    // which onboarding pages should this plugin be hidden on
    // e.g. geolocation doesn't apply to session replay
    productOnboardingDenyList?: ProductKey[]
}

type PluginContentMapping = Record<string, PluginContent>
export const pluginContentMapping: PluginContentMapping = {
    GeoIP: {
        title: 'Capture location information',
        description:
            'Enrich PostHog events and persons with IP location data. This is useful for understanding where your users are coming from. This setting can be found under data pipeline.',
        productOnboardingDenyList: [ProductKey.SESSION_REPLAY],
    },
}

export interface DefaultEnabledType {
    title: string
    description?: string
    productOnboardingDenyList?: ProductKey[]
    id: number
    enabled: boolean
}

export const pipelineDefaultEnabledLogic = kea<pipelineDefaultEnabledLogicType>([
    path(['scenes', 'pipeline', 'pipelineDefaultEnabledLogic']),
    connect({
        values: [pipelineTransformationsLogic, ['plugins', 'pluginConfigs']],
        actions: [pipelineTransformationsLogic, ['toggleEnabled']],
    }),
    selectors({
        pipelineDefaultEnabled: [
            (s) => [s.plugins, s.pluginConfigs],
            (plugins, pluginConfigs): DefaultEnabledType[] => {
                const defaultEnabledPluginIds = Object.values(plugins)
                    .filter((plugin) => plugin.name in pluginContentMapping)
                    .map((plugin) => plugin.id)
                const defaultEnabledPluginConfigs = Object.values(pluginConfigs).filter((pluginConfig) =>
                    defaultEnabledPluginIds.includes(pluginConfig.plugin)
                )
                return defaultEnabledPluginConfigs.map((pluginConfig) => {
                    const plugin = plugins[pluginConfig.plugin]
                    const pluginContent = pluginContentMapping[plugin.name]
                    return {
                        title: pluginContent?.title || plugin.name,
                        description: pluginContent?.description || plugin.description,
                        productOnboardingDenyList: pluginContent?.productOnboardingDenyList,
                        id: pluginConfig.id,
                        enabled: pluginConfig.enabled,
                    }
                })
            },
        ],
    }),
])
