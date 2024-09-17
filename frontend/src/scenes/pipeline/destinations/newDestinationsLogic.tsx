import FuseClass from 'fuse.js'
import { actions, afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, router } from 'kea-router'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    BATCH_EXPORT_SERVICE_NAMES,
    BatchExportService,
    HogFunctionTemplateStatus,
    HogFunctionTemplateType,
    PipelineStage,
    PluginType,
} from '~/types'

import { humanizeBatchExportName } from '../batch-exports/utils'
import { HogFunctionIcon } from '../hogfunctions/HogFunctionIcon'
import { PipelineBackend } from '../types'
import { loadPluginsFromUrl, RenderApp, RenderBatchExportIcon } from '../utils'
import { destinationsFiltersLogic } from './destinationsFiltersLogic'
import type { newDestinationsLogicType } from './newDestinationsLogicType'

export type NewDestinationItemType = {
    icon: JSX.Element
    url: string
    name: string
    description: string
    backend: PipelineBackend
    status?: HogFunctionTemplateStatus
}

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<NewDestinationItemType> {}

export const newDestinationsLogic = kea<newDestinationsLogicType>([
    path(() => ['scenes', 'pipeline', 'destinations', 'newDestinationsLogic']),
    connect({
        values: [userLogic, ['user'], featureFlagLogic, ['featureFlags'], destinationsFiltersLogic, ['filters']],
    }),
    actions({
        openFeedbackDialog: true,
    }),
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
            (s) => [s.user, s.featureFlags],
            (user, featureFlags): BatchExportService['type'][] => {
                const httpEnabled =
                    featureFlags[FEATURE_FLAGS.BATCH_EXPORTS_POSTHOG_HTTP] || user?.is_impersonated || user?.is_staff
                // HTTP is currently only used for Cloud to Cloud migrations and shouldn't be accessible to users
                const services: BatchExportService['type'][] = BATCH_EXPORT_SERVICE_NAMES.filter((service) =>
                    httpEnabled ? true : service !== ('HTTP' as const)
                )
                return services
            },
        ],
        destinations: [
            (s) => [
                s.plugins,
                s.hogFunctionTemplates,
                s.batchExportServiceNames,
                s.featureFlags,
                router.selectors.hashParams,
            ],
            (
                plugins,
                hogFunctionTemplates,
                batchExportServiceNames,
                featureFlags,
                hashParams
            ): NewDestinationItemType[] => {
                const hogFunctionsEnabled = !!featureFlags[FEATURE_FLAGS.HOG_FUNCTIONS]
                const hogTemplates = hogFunctionsEnabled ? Object.values(hogFunctionTemplates) : []

                return [
                    ...hogTemplates.map((hogFunction) => ({
                        icon: <HogFunctionIcon size="small" src={hogFunction.icon_url} />,
                        name: hogFunction.name,
                        description: hogFunction.description,
                        backend: PipelineBackend.HogFunction,
                        url: combineUrl(
                            urls.pipelineNodeNew(PipelineStage.Destination, `hog-${hogFunction.id}`),
                            {},
                            hashParams
                        ).url,
                        status: hogFunction.status,
                    })),
                    ...Object.values(plugins)
                        .filter((x) => !hogFunctionsEnabled || !x.hog_function_migration_available)
                        .map((plugin) => ({
                            icon: <RenderApp plugin={plugin} />,
                            name: plugin.name,
                            description: plugin.description || '',
                            backend: PipelineBackend.Plugin,
                            url: urls.pipelineNodeNew(PipelineStage.Destination, `${plugin.id}`),
                            status: hogFunctionsEnabled ? ('deprecated' as const) : undefined,
                        })),
                    ...batchExportServiceNames.map((service) => ({
                        icon: <RenderBatchExportIcon type={service} />,
                        name: humanizeBatchExportName(service),
                        description: `${service} batch export`,
                        backend: PipelineBackend.BatchExport,
                        url: urls.pipelineNodeNew(PipelineStage.Destination, `${service}`),
                    })),
                ]
            },
        ],

        destinationsFuse: [
            (s) => [s.destinations],
            (destinations): Fuse => {
                return new FuseClass(destinations || [], {
                    keys: ['name', 'description'],
                    threshold: 0.3,
                })
            },
        ],

        filteredDestinations: [
            (s) => [s.filters, s.destinations, s.destinationsFuse],
            (filters, destinations, destinationsFuse): NewDestinationItemType[] => {
                const { search, kind } = filters

                return (search ? destinationsFuse.search(search).map((x) => x.item) : destinations).filter((dest) => {
                    if (kind && dest.backend !== kind) {
                        return false
                    }
                    return true
                })
            },
        ],

        hiddenDestinations: [
            (s) => [s.destinations, s.filteredDestinations],
            (destinations, filteredDestinations): NewDestinationItemType[] => {
                return destinations.filter((dest) => !filteredDestinations.includes(dest))
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadHogFunctionTemplates()
    }),
])
