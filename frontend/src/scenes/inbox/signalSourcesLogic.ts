import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'

import { ExternalDataSourceType } from '~/queries/schema/schema-general'
import { SignalSourceProduct, SignalSourceType } from '~/queries/schema/schema-signals'
import { ExternalDataSource, ExternalDataSourceSchema, RecordingUniversalFilters } from '~/types'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'

import type { signalSourcesLogicType } from './signalSourcesLogicType'
import { SignalSourceConfig, SignalSourceConfigStatus, ToggleSignalSourceParams } from './types'

export type DataWarehouseSource = 'Linear' | 'Zendesk' | 'Github'

/** Matches Cymbal `EmitSignalRequest.source_type` + `products.signals.backend.api.emit_signal` checks. */
export const ERROR_TRACKING_SIGNAL_SOURCE_TYPES: SignalSourceType[] = [
    SignalSourceType.ISSUE_CREATED,
    SignalSourceType.ISSUE_REOPENED,
    SignalSourceType.ISSUE_SPIKING,
]

const DATA_WAREHOUSE_SOURCE_CONFIG: Record<
    DataWarehouseSource,
    {
        sourceProduct: SignalSourceProduct
        sourceType: SignalSourceType
        requiredTable: 'issues' | 'tickets'
        enableErrorMessage: string
    }
> = {
    Github: {
        sourceProduct: SignalSourceProduct.GITHUB,
        sourceType: SignalSourceType.ISSUE,
        requiredTable: 'issues',
        enableErrorMessage: 'Failed to enable GitHub Issues',
    },
    Linear: {
        sourceProduct: SignalSourceProduct.LINEAR,
        sourceType: SignalSourceType.ISSUE,
        requiredTable: 'issues',
        enableErrorMessage: 'Failed to enable Linear Issues',
    },
    Zendesk: {
        sourceProduct: SignalSourceProduct.ZENDESK,
        sourceType: SignalSourceType.TICKET,
        requiredTable: 'tickets',
        enableErrorMessage: 'Failed to enable Zendesk Tickets',
    },
}

/** Values subset used by data-warehouse source helpers */
interface SignalSourcesLogicValuesForDw {
    githubIssuesConfig: SignalSourceConfig | null
    linearIssuesConfig: SignalSourceConfig | null
    zendeskTicketsConfig: SignalSourceConfig | null
}

function getDataWarehouseSourceConfig(
    values: SignalSourcesLogicValuesForDw,
    dwSource: DataWarehouseSource
): SignalSourceConfig | null {
    if (dwSource === 'Github') {
        return values.githubIssuesConfig
    }
    if (dwSource === 'Linear') {
        return values.linearIssuesConfig
    }
    return values.zendeskTicketsConfig
}

function toggleSourceConfigState(
    state: SignalSourceConfig[] | null,
    sourceProduct: SignalSourceProduct,
    sourceType: SignalSourceType
): SignalSourceConfig[] | null {
    if (!state) {
        return state
    }
    const existing = state.find((c) => c.source_product === sourceProduct && c.source_type === sourceType)
    if (existing) {
        return state.map((c) =>
            c.source_product === sourceProduct && c.source_type === sourceType ? { ...c, enabled: !c.enabled } : c
        )
    }
    return [
        ...state,
        {
            id: `new_${sourceProduct}_${sourceType}`,
            source_product: sourceProduct,
            source_type: sourceType,
            enabled: true,
            config: {},
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            status: null,
        },
    ]
}

export const signalSourcesLogic = kea<signalSourcesLogicType>([
    path(['scenes', 'inbox', 'signalSourcesLogic']),

    connect(() => ({
        values: [sourcesDataLogic, ['dataWarehouseSources', 'dataWarehouseSourcesLoading']],
        actions: [sourcesDataLogic, ['loadSources']],
    })),

    actions({
        openSourcesModal: true,
        closeSourcesModal: true,
        openSessionAnalysisSetup: true,
        closeSessionAnalysisSetup: true,
        toggleSessionAnalysis: true,
        toggleDataWarehouseSource: (dwSource: DataWarehouseSource) => ({ dwSource }),
        initiateDataWarehouseSourceToggle: (dwSource: DataWarehouseSource) => ({ dwSource }),
        openDataSourceSetup: (product: ExternalDataSourceType) => ({ product }),
        closeDataSourceSetup: true,
        onDataSourceSetupComplete: (product: ExternalDataSourceType) => ({ product }),
        toggleSignalSource: (params: ToggleSignalSourceParams) => ({ params }),
        toggleSignalSourceSuccess: (params: ToggleSignalSourceParams) => ({ params }),
        toggleSignalSourceFailure: (params: ToggleSignalSourceParams, error: string) => ({ params, error }),
        toggleErrorTracking: true,
        toggleErrorTrackingComplete: true,
        saveSessionAnalysisFilters: (filters: RecordingUniversalFilters) => ({ filters }),
        clearSessionAnalysisFilters: true,
    }),

    loaders({
        sourceConfigs: [
            null as SignalSourceConfig[] | null,
            {
                loadSourceConfigs: async () => {
                    const response = await api.signalSourceConfigs.list()
                    return response.results
                },
            },
        ],
    }),

    reducers({
        sourcesModalOpen: [
            false,
            {
                openSourcesModal: () => true,
                closeSourcesModal: () => false,
            },
        ],
        sessionAnalysisSetupOpen: [
            false,
            {
                openSourcesModal: () => false,
                openSessionAnalysisSetup: () => true,
                closeSessionAnalysisSetup: () => false,
            },
        ],
        dataSourceSetupProduct: [
            null as ExternalDataSourceType | null,
            {
                openDataSourceSetup: (_, { product }) => product,
                closeDataSourceSetup: () => null,
                closeSourcesModal: () => null,
            },
        ],
        sourceConfigs: {
            toggleSessionAnalysis: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(
                    state,
                    SignalSourceProduct.SESSION_REPLAY,
                    SignalSourceType.SESSION_ANALYSIS_CLUSTER
                ),
            toggleDataWarehouseSource: (state: SignalSourceConfig[] | null, { dwSource }) => {
                const { sourceProduct, sourceType } = DATA_WAREHOUSE_SOURCE_CONFIG[dwSource]
                return toggleSourceConfigState(state, sourceProduct, sourceType)
            },
        },
        togglingSourceKeys: [
            new Set<string>(),
            {
                toggleSignalSource: (state, { params }) => {
                    const next = new Set(state)
                    next.add(`${params.sourceProduct}_${params.sourceType}`)
                    return next
                },
                toggleSignalSourceSuccess: (state, { params }) => {
                    const next = new Set(state)
                    next.delete(`${params.sourceProduct}_${params.sourceType}`)
                    return next
                },
                toggleSignalSourceFailure: (state, { params }) => {
                    const next = new Set(state)
                    next.delete(`${params.sourceProduct}_${params.sourceType}`)
                    return next
                },
                toggleErrorTracking: (state) => {
                    const next = new Set(state)
                    next.add('error_tracking')
                    return next
                },
                toggleErrorTrackingComplete: (state) => {
                    const next = new Set(state)
                    next.delete('error_tracking')
                    return next
                },
            },
        ],
    }),

    selectors({
        sessionAnalysisConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.SESSION_REPLAY &&
                        c.source_type === SignalSourceType.SESSION_ANALYSIS_CLUSTER
                ) ?? null,
        ],
        githubIssuesConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) => c.source_product === SignalSourceProduct.GITHUB && c.source_type === SignalSourceType.ISSUE
                ) ?? null,
        ],
        linearIssuesConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) => c.source_product === SignalSourceProduct.LINEAR && c.source_type === SignalSourceType.ISSUE
                ) ?? null,
        ],
        zendeskTicketsConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) => c.source_product === SignalSourceProduct.ZENDESK && c.source_type === SignalSourceType.TICKET
                ) ?? null,
        ],
        isSessionAnalysisToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean =>
                keys.has(`${SignalSourceProduct.SESSION_REPLAY}_${SignalSourceType.SESSION_ANALYSIS_CLUSTER}`),
        ],
        isGithubIssuesToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.GITHUB}_${SignalSourceType.ISSUE}`),
        ],
        isLinearIssuesToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.LINEAR}_${SignalSourceType.ISSUE}`),
        ],
        isZendeskTicketsToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.ZENDESK}_${SignalSourceType.TICKET}`),
        ],
        isErrorTrackingToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has('error_tracking'),
        ],
        errorTrackingIsFullyEnabled: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): boolean => {
                if (!sourceConfigs?.length) {
                    return false
                }
                return ERROR_TRACKING_SIGNAL_SOURCE_TYPES.every((sourceType) => {
                    const c = sourceConfigs.find(
                        (row) =>
                            row.source_product === SignalSourceProduct.ERROR_TRACKING && row.source_type === sourceType
                    )
                    return c?.enabled === true
                })
            },
        ],
        isClusteringRunning: [
            (s) => [s.sessionAnalysisConfig],
            (config: SignalSourceConfig | null): boolean => config?.status === SignalSourceConfigStatus.RUNNING,
        ],
        enabledSourcesCount: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): number => sourceConfigs?.filter((c) => c.enabled).length ?? 0,
        ],
        hasNoSources: [
            (s) => [s.sourceConfigs, s.enabledSourcesCount],
            (sourceConfigs: SignalSourceConfig[] | null, enabledSourcesCount: number): boolean =>
                sourceConfigs !== null && enabledSourcesCount === 0,
        ],
    }),

    listeners(({ actions, values }) => {
        // If the required table for a signal source is not yet syncing on the existing DW source,
        // enable it so the signals workflow has data to process.
        async function ensureRequiredTableSyncing(dwSourceType: string, tableName: string): Promise<void> {
            const source = values.dataWarehouseSources?.results?.find(
                (s: ExternalDataSource) => s.source_type === dwSourceType
            )
            if (!source) {
                return
            }
            const schema = source.schemas?.find((s: ExternalDataSourceSchema) => s.name === tableName)
            if (schema && !schema.should_sync) {
                await api.externalDataSchemas.update(schema.id, { should_sync: true })
            }
        }

        return {
            openSourcesModal: () => {
                // Load external data sources so we can check connectivity when user toggles a source
                actions.loadSources()
            },
            initiateDataWarehouseSourceToggle: async ({ dwSource }) => {
                const { requiredTable, enableErrorMessage } = DATA_WAREHOUSE_SOURCE_CONFIG[dwSource]
                const sourceConfig = getDataWarehouseSourceConfig(values, dwSource)
                const isCurrentlyEnabled = sourceConfig?.enabled === true
                if (!isCurrentlyEnabled) {
                    const hasSource =
                        values.dataWarehouseSources?.results?.some(
                            (s: ExternalDataSource) => s.source_type === dwSource
                        ) ?? false
                    if (!hasSource) {
                        actions.openDataSourceSetup(dwSource)
                        return
                    }
                    try {
                        await ensureRequiredTableSyncing(dwSource, requiredTable)
                    } catch (error: any) {
                        lemonToast.error(error?.detail || error?.message || enableErrorMessage)
                        return
                    }
                }
                actions.toggleDataWarehouseSource(dwSource)
            },
            onDataSourceSetupComplete: ({ product }: { product: ExternalDataSourceType }) => {
                const mapping: Partial<
                    Record<ExternalDataSourceType, { sourceProduct: SignalSourceProduct; sourceType: SignalSourceType }>
                > = {
                    Github: { sourceProduct: SignalSourceProduct.GITHUB, sourceType: SignalSourceType.ISSUE },
                    Linear: { sourceProduct: SignalSourceProduct.LINEAR, sourceType: SignalSourceType.ISSUE },
                    Zendesk: { sourceProduct: SignalSourceProduct.ZENDESK, sourceType: SignalSourceType.TICKET },
                }
                const mapped = mapping[product]
                if (mapped) {
                    actions.toggleSignalSource({ ...mapped, enabled: true })
                }
                actions.closeDataSourceSetup()
            },
            toggleSignalSource: async ({ params }, breakpoint) => {
                const { sourceProduct, sourceType, enabled, config } = params
                try {
                    const configs = values.sourceConfigs ?? []
                    const existing = configs.find(
                        (c: SignalSourceConfig) => c.source_product === sourceProduct && c.source_type === sourceType
                    )

                    if (existing && !existing.id.startsWith('new_')) {
                        const updateData: Partial<SignalSourceConfig> = { enabled }
                        if (config !== undefined) {
                            updateData.config = config
                        }
                        await api.signalSourceConfigs.update(existing.id, updateData)
                    } else if (enabled) {
                        await api.signalSourceConfigs.create({
                            source_product: sourceProduct,
                            source_type: sourceType,
                            enabled,
                            config: config ?? {},
                        })
                    }
                    breakpoint()
                    actions.toggleSignalSourceSuccess(params)
                    actions.loadSourceConfigs()
                } catch (error: any) {
                    breakpoint()
                    const errorMessage = error?.detail || error?.message || 'Failed to toggle signal source'
                    actions.toggleSignalSourceFailure(params, errorMessage)
                    actions.loadSourceConfigs()
                    lemonToast.error(errorMessage)
                }
            },
            toggleErrorTracking: async (_, breakpoint) => {
                const desiredEnabled = !values.errorTrackingIsFullyEnabled
                const configs = values.sourceConfigs ?? []
                try {
                    for (const sourceType of ERROR_TRACKING_SIGNAL_SOURCE_TYPES) {
                        const existing = configs.find(
                            (c) =>
                                c.source_product === SignalSourceProduct.ERROR_TRACKING && c.source_type === sourceType
                        )
                        if (existing && !existing.id.startsWith('new_')) {
                            await api.signalSourceConfigs.update(existing.id, { enabled: desiredEnabled })
                        } else if (desiredEnabled) {
                            await api.signalSourceConfigs.create({
                                source_product: SignalSourceProduct.ERROR_TRACKING,
                                source_type: sourceType,
                                enabled: true,
                                config: {},
                            })
                        }
                    }
                    breakpoint()
                    actions.toggleErrorTrackingComplete()
                    actions.loadSourceConfigs()
                } catch (error: any) {
                    breakpoint() // re-throws if superseded, skipping the lines below
                    actions.toggleErrorTrackingComplete()
                    const errorMessage = error?.detail || error?.message || 'Failed to toggle Error tracking signals'
                    lemonToast.error(errorMessage)
                    actions.loadSourceConfigs()
                }
            },
            toggleSessionAnalysis: () => {
                const config = values.sessionAnalysisConfig
                const desiredEnabled = config?.enabled ?? true
                actions.toggleSignalSource({
                    sourceProduct: SignalSourceProduct.SESSION_REPLAY,
                    sourceType: SignalSourceType.SESSION_ANALYSIS_CLUSTER,
                    enabled: desiredEnabled,
                })
            },
            toggleDataWarehouseSource: ({ dwSource }) => {
                const { sourceProduct, sourceType } = DATA_WAREHOUSE_SOURCE_CONFIG[dwSource]
                const config = getDataWarehouseSourceConfig(values, dwSource)
                const desiredEnabled = config?.enabled ?? true
                actions.toggleSignalSource({
                    sourceProduct,
                    sourceType,
                    enabled: desiredEnabled,
                })
            },
            saveSessionAnalysisFilters: async ({ filters }) => {
                try {
                    const existing = values.sessionAnalysisConfig
                    if (existing) {
                        await api.signalSourceConfigs.update(existing.id, {
                            config: { recording_filters: filters },
                            enabled: true,
                        })
                    } else {
                        await api.signalSourceConfigs.create({
                            source_product: SignalSourceProduct.SESSION_REPLAY,
                            source_type: SignalSourceType.SESSION_ANALYSIS_CLUSTER,
                            config: { recording_filters: filters },
                            enabled: true,
                        })
                    }
                    lemonToast.success('Session analysis filters saved')
                    actions.loadSourceConfigs()
                    actions.closeSessionAnalysisSetup()
                } catch (error: any) {
                    const errorMessage = error?.detail || error?.message || 'Failed to save filters'
                    lemonToast.error(errorMessage)
                }
            },
            clearSessionAnalysisFilters: async () => {
                try {
                    const existing = values.sessionAnalysisConfig
                    if (
                        existing &&
                        existing.id !==
                            `new_${SignalSourceProduct.SESSION_REPLAY}_${SignalSourceType.SESSION_ANALYSIS_CLUSTER}`
                    ) {
                        await api.signalSourceConfigs.update(existing.id, { config: {}, enabled: true })
                        lemonToast.success('Session analysis filters cleared')
                    }
                    actions.loadSourceConfigs()
                } catch (error: any) {
                    const errorMessage = error?.detail || error?.message || 'Failed to clear filters'
                    lemonToast.error(errorMessage)
                }
            },
        }
    }),

    events(({ actions }) => ({
        afterMount: () => {
            if (posthog.isFeatureEnabled(FEATURE_FLAGS.PRODUCT_AUTONOMY)) {
                // The condition allows us to safely mount this logic for user without the product autonomy feature flag
                // without needlessly loading the source configs
                actions.loadSourceConfigs()
            }
        },
    })),
])
