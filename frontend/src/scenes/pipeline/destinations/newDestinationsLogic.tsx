import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { BATCH_EXPORT_SERVICE_NAMES, BatchExportService, HogFunctionTemplateType, PluginType } from '~/types'

import { HogFunctionIcon } from '../hogfunctions/HogFunctionIcon'
import { loadPluginsFromUrl, RenderApp, RenderBatchExportIcon } from '../utils'

export type NewDestinationItemType = {
    icon: JSX.Element
    name: string
    description: string
    kind: 'plugin' | 'batchExport' | 'hogFunction'
    status?: 'stable' | 'beta' | 'alpha'
}

export const newDestinationsLogic = kea([
    connect({
        values: [userLogic, ['user']],
    }),
    path(() => ['scenes', 'pipeline', 'destinations', 'newDestinationsLogic']),
    loaders({
        plugins: [
            {} as Record<number, PluginType>,
            {
                loadPlugins: async () => {
                    return loadPluginsFromUrl('api/organizations/@current/pipeline_destinations')
                },
            },
        ],
        hogFunctionTemplates: [
            {} as Record<string, HogFunctionTemplateType>,
            {
                loadHogFunctionTemplates: async () => {
                    const templates = await api.hogFunctions.listTemplates()
                    return templates.results.reduce((acc, template) => {
                        acc[template.id] = template
                        return acc
                    }, {} as Record<string, HogFunctionTemplateType>)
                },
            },
        ],
    }),

    selectors(() => ({
        loading: [
            (s) => [s.pluginsLoading, s.hogFunctionTemplatesLoading],
            (pluginsLoading, hogFunctionTemplatesLoading) => pluginsLoading || hogFunctionTemplatesLoading,
        ],
        batchExportServiceNames: [
            (s) => [s.user],
            (user): BatchExportService['type'][] => {
                // HTTP is currently only used for Cloud to Cloud migrations and shouldn't be accessible to users
                const services: BatchExportService['type'][] = BATCH_EXPORT_SERVICE_NAMES.filter(
                    (service) => service !== 'HTTP'
                ) as BatchExportService['type'][]
                if (user?.is_impersonated || user?.is_staff) {
                    services.push('HTTP')
                }
                return services
            },
        ],

        destinations: [
            (s) => [s.plugins, s.hogFunctionTemplates, s.batchExportServiceNames],
            (plugins, hogFunctionTemplates, batchExportServiceNames): NewDestinationItemType[] => {
                return [
                    ...Object.values(plugins).map((plugin) => ({
                        icon: <RenderApp plugin={plugin} />,
                        name: plugin.name,
                        description: plugin.description || '',
                        kind: 'plugin',
                        status: plugin.status,
                    })),
                    ...Object.values(hogFunctionTemplates).map((hogFunction) => ({
                        icon: <HogFunctionIcon size="small" src={hogFunction.icon_url} />,
                        name: hogFunction.name,
                        description: hogFunction.description,
                        kind: 'hogFunction',
                    })),
                    ...batchExportServiceNames.map((service) => ({
                        icon: <RenderBatchExportIcon type={service} />,
                        name: service,
                        description: `${service} batch export`,
                        kind: 'batchExport',
                    })),
                ]
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadHogFunctionTemplates()
    }),
])
