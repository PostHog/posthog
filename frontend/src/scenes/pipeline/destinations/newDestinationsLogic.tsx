import { LemonDialog, LemonInput, LemonTextArea, lemonToast } from '@posthog/lemon-ui'
import FuseClass from 'fuse.js'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import posthog from 'posthog-js'
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
import type { newDestinationsLogicType } from './newDestinationsLogicType'

export type NewDestinationItemType = {
    icon: JSX.Element
    url: string
    name: string
    description: string
    backend: PipelineBackend
    status?: HogFunctionTemplateStatus
}

export type NewDestinationFilters = {
    search?: string
    kind?: PipelineBackend
    sub_template?: string
}

export type NewDestinationsLogicProps = {
    defaultFilters?: NewDestinationFilters
    forceFilters?: NewDestinationFilters
}

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<NewDestinationItemType> {}

export const newDestinationsLogic = kea<newDestinationsLogicType>([
    path(() => ['scenes', 'pipeline', 'destinations', 'newDestinationsLogic']),
    connect({
        values: [userLogic, ['user'], featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setFilters: (filters: Partial<NewDestinationFilters>) => ({ filters }),
        resetFilters: true,
        openFeedbackDialog: true,
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
    })),

    listeners(({ values }) => ({
        setFilters: async ({ filters }, breakpoint) => {
            if (filters.search && filters.search.length > 2) {
                await breakpoint(1000)
                posthog.capture('cdp destination search', { search: filters.search })
            }
        },

        openFeedbackDialog: async (_, breakpoint) => {
            await breakpoint(100)
            LemonDialog.openForm({
                title: 'What destination would you like to see?',
                initialValues: { destination_name: values.filters.search },
                errors: {
                    destination_name: (x) => (!x ? 'Required' : undefined),
                },
                description: undefined,
                content: (
                    <div className="space-y-2">
                        <LemonField name="destination_name" label="Destination">
                            <LemonInput placeholder="What destination would you like to see?" autoFocus />
                        </LemonField>
                        <LemonField name="destination_details" label="Additional information" showOptional>
                            <LemonTextArea placeholder="Any extra details about what you would need this destination to do or your overall goal" />
                        </LemonField>
                    </div>
                ),
                onSubmit: async (values) => {
                    posthog.capture('cdp destination feedback', { ...values })
                    lemonToast.success('Thank you for your feedback!')
                },
            })
        },
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
