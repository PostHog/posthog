import FuseClass from 'fuse.js'
import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { objectsEqual } from 'lib/utils'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    BATCH_EXPORT_SERVICE_NAMES,
    BatchExportService,
    HogFunctionTemplateType,
    PipelineStage,
    PluginType,
} from '~/types'

import { HogFunctionIcon } from '../hogfunctions/HogFunctionIcon'
import { PipelineBackend } from '../types'
import { loadPluginsFromUrl, RenderApp, RenderBatchExportIcon } from '../utils'
import type { newDestinationsLogicType } from './newDestinationsLogicType'

export type NewDestinationItemType = {
    icon: JSX.Element
    url: string
    name: string
    description: string
    backend: PipelineBackend
    status?: 'stable' | 'beta' | 'alpha'
}

export type NewDestinationFilters = {
    search?: string
    kind?: PipelineBackend
}

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<NewDestinationItemType> {}

export const newDestinationsLogic = kea<newDestinationsLogicType>([
    connect({
        values: [userLogic, ['user']],
    }),
    path(() => ['scenes', 'pipeline', 'destinations', 'newDestinationsLogic']),
    actions({
        setFilters: (filters: Partial<NewDestinationFilters>) => ({ filters }),
        resetFilters: true,
    }),
    reducers({
        filters: [
            {} as NewDestinationFilters,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                resetFilters: () => ({}),
            },
        ],
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
            (s) => [s.plugins, s.hogFunctionTemplates, s.batchExportServiceNames, router.selectors.hashParams],
            (plugins, hogFunctionTemplates, batchExportServiceNames, hashParams): NewDestinationItemType[] => {
                return [
                    ...Object.values(plugins).map((plugin) => ({
                        icon: <RenderApp plugin={plugin} />,
                        name: plugin.name,
                        description: plugin.description || '',
                        backend: PipelineBackend.Plugin,
                        url: urls.pipelineNodeNew(PipelineStage.Destination, `${plugin.id}`),
                    })),
                    ...Object.values(hogFunctionTemplates).map((hogFunction) => ({
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
                    ...batchExportServiceNames.map((service) => ({
                        icon: <RenderBatchExportIcon type={service} />,
                        name: service,
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
    })),

    actionToUrl(({ values }) => {
        const urlFromFilters = (): [
            string,
            Record<string, any>,
            Record<string, any>,
            {
                replace: boolean
            }
        ] => [
            router.values.location.pathname,
            {
                ...values.filters,
            },
            router.values.hashParams,
            {
                replace: true,
            },
        ]

        return {
            setFilters: () => urlFromFilters(),
            resetFilters: () => urlFromFilters(),
        }
    }),

    urlToAction(({ actions, values }) => ({
        '*': (_, searchParams) => {
            if (!objectsEqual(values.filters, searchParams)) {
                actions.setFilters(searchParams)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadHogFunctionTemplates()
    }),
])
