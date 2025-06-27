import FuseClass from 'fuse.js'
import { actions, afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, router } from 'kea-router'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { RenderBatchExportIcon } from 'scenes/data-pipelines/batch-exports/BatchExportIcon'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { shouldShowHogFunctionTemplate } from 'scenes/hog-functions/list/hogFunctionTemplateListLogic'
import { hogFunctionTypeToPipelineStage } from 'scenes/hog-functions/misc/urls'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { BATCH_EXPORT_SERVICE_NAMES, BatchExportService, HogFunctionTemplateType, PipelineStage } from '~/types'

import { humanizeBatchExportName } from '../../data-pipelines/batch-exports/utils'
import { NewDestinationItemType, PipelineBackend } from '../types'
import { destinationsFiltersLogic } from './destinationsFiltersLogic'
import { PipelineDestinationsLogicProps } from './destinationsLogic'
import type { newDestinationsLogicType } from './newDestinationsLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<NewDestinationItemType> {}

export const getDestinationDocPath = (url: string): string => {
    return url.split('/').pop()?.replace('hog-', '') || ''
}

export const newDestinationsLogic = kea<newDestinationsLogicType>([
    path(() => ['scenes', 'pipeline', 'destinations', 'newDestinationsLogic']),
    props({} as PipelineDestinationsLogicProps),
    key((props) => props.types.join(',') ?? ''),
    connect(({ types }: PipelineDestinationsLogicProps) => ({
        values: [
            userLogic,
            ['user'],
            featureFlagLogic,
            ['featureFlags'],
            destinationsFiltersLogic({ types }),
            ['filters'],
        ],
    })),
    actions({
        openFeedbackDialog: true,
    }),
    loaders(({ props, values }) => ({
        hogFunctionTemplates: [
            {} as Record<string, HogFunctionTemplateType>,
            {
                loadHogFunctionTemplates: async () => {
                    const siteDesinationsEnabled = !!values.featureFlags[FEATURE_FLAGS.SITE_DESTINATIONS]
                    const destinationTypes = siteDesinationsEnabled
                        ? props.types
                        : props.types.filter((type) => type !== 'site_destination')
                    const dbTemplates = !!values.featureFlags[FEATURE_FLAGS.GET_HOG_TEMPLATES_FROM_DB]
                    const templates = await api.hogFunctions.listTemplates({
                        types: destinationTypes,
                        db_templates: dbTemplates,
                    })
                    return templates.results.reduce((acc, template) => {
                        acc[template.id] = template
                        return acc
                    }, {} as Record<string, HogFunctionTemplateType>)
                },
            },
        ],
    })),

    selectors(() => ({
        loading: [(s) => [s.hogFunctionTemplatesLoading], (hogFunctionTemplatesLoading) => hogFunctionTemplatesLoading],
        types: [() => [(_, p) => p.types], (types) => types],
        batchExportServiceNames: [
            (s) => [s.user, s.featureFlags, s.types],
            (user, featureFlags, types): BatchExportService['type'][] => {
                // Only add batch exports on the "destinations" page
                if (!types.includes('destination')) {
                    return []
                }
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
            (s) => [s.hogFunctionTemplates, s.batchExportServiceNames, router.selectors.hashParams, s.user],
            (hogFunctionTemplates, batchExportServiceNames, hashParams, user): NewDestinationItemType[] => {
                return [
                    ...Object.values(hogFunctionTemplates)
                        .filter((hogFunction) => shouldShowHogFunctionTemplate(hogFunction, user))
                        .map((hogFunction) => ({
                            icon: <HogFunctionIcon size="small" src={hogFunction.icon_url} />,
                            name: hogFunction.name,
                            description: typeof hogFunction.description === 'string' ? hogFunction.description : '',
                            backend: PipelineBackend.HogFunction as const,
                            url: combineUrl(
                                urls.pipelineNodeNew(hogFunctionTypeToPipelineStage(hogFunction.type), {
                                    id: `hog-${hogFunction.id}`,
                                }),
                                {},
                                hashParams
                            ).url,
                            status: hogFunction.status,
                            free: hogFunction.free,
                        })),
                    ...batchExportServiceNames.map((service) => ({
                        icon: <RenderBatchExportIcon type={service} />,
                        name: humanizeBatchExportName(service),
                        description: `${service} batch export`,
                        backend: PipelineBackend.BatchExport as const,
                        url: urls.pipelineNodeNew(PipelineStage.Destination, { id: service }),
                        free: false,
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
        actions.loadHogFunctionTemplates()
    }),
])
