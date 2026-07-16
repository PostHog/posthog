import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SignalSourceProduct, SignalSourceType } from 'scenes/inbox/types'

import { ExternalDataSourceType } from '~/queries/schema/schema-general'
import { ExternalDataSource, ExternalDataSourceSchema, RecordingUniversalFilters } from '~/types'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'

import { captureSignalSourceConnected } from './inboxAnalytics'
import type { signalSourcesLogicType } from './signalSourcesLogicType'
import { SignalSourceConfig, SignalSourceConfigStatus, ToggleSignalSourceParams } from './types'

/** Matches Cymbal `EmitSignalRequest.source_type` + `products.signals.backend.api.emit_signal` checks. */
export const ERROR_TRACKING_SIGNAL_SOURCE_TYPES: SignalSourceType[] = [
    SignalSourceType.IssueCreated,
    SignalSourceType.IssueReopened,
    SignalSourceType.IssueSpiking,
]

/**
 * One registration per warehouse-backed signal source: the warehouse product that backs it, the
 * tables its signals read (pre-selected in the wizard and forced to sync), and the config row that
 * enabling creates. Keyed by signal source, not warehouse product, so one product can back several
 * sources.
 */
export const WAREHOUSE_SOURCE_SETUP = {
    github: {
        dwSourceType: 'Github',
        requiredTables: ['issues'],
        sourceProduct: SignalSourceProduct.Github,
        sourceType: SignalSourceType.Issue,
        enableErrorMessage: 'Failed to enable GitHub Issues',
    },
    linear: {
        dwSourceType: 'Linear',
        requiredTables: ['issues'],
        sourceProduct: SignalSourceProduct.Linear,
        sourceType: SignalSourceType.Issue,
        enableErrorMessage: 'Failed to enable Linear Issues',
    },
    zendesk: {
        dwSourceType: 'Zendesk',
        requiredTables: ['tickets'],
        sourceProduct: SignalSourceProduct.Zendesk,
        sourceType: SignalSourceType.Ticket,
        enableErrorMessage: 'Failed to enable Zendesk Tickets',
    },
    pganalyze: {
        dwSourceType: 'PgAnalyze',
        requiredTables: ['issues', 'servers'],
        sourceProduct: SignalSourceProduct.Pganalyze,
        sourceType: SignalSourceType.Issue,
        enableErrorMessage: 'Failed to enable pganalyze',
    },
} satisfies Record<
    string,
    {
        dwSourceType: ExternalDataSourceType
        requiredTables: string[]
        sourceProduct: SignalSourceProduct
        sourceType: SignalSourceType
        enableErrorMessage: string
    }
>

/** Warehouse-backed signal sources, keyed by roster source id. */
export type WarehouseBackedSource = keyof typeof WAREHOUSE_SOURCE_SETUP

/** GitHub names multi-repo rows `owner/repo.issues` and every repo feeds the source, so enable them all. */
export function schemasToEnableFor(source: ExternalDataSource, tableName: string): ExternalDataSourceSchema[] {
    return (source.schemas ?? []).filter(
        (schema: ExternalDataSourceSchema) =>
            !schema.should_sync && (schema.name === tableName || schema.name.endsWith(`.${tableName}`))
    )
}

function getWarehouseSourceConfig(
    sourceConfigs: SignalSourceConfig[] | null,
    source: WarehouseBackedSource
): SignalSourceConfig | null {
    const { sourceProduct, sourceType } = WAREHOUSE_SOURCE_SETUP[source]
    return sourceConfigs?.find((c) => c.source_product === sourceProduct && c.source_type === sourceType) ?? null
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
        values: [
            sourcesDataLogic,
            ['dataWarehouseSources', 'dataWarehouseSourcesLoading'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [sourcesDataLogic, ['loadSources']],
    })),

    actions({
        openSourcesModal: true,
        closeSourcesModal: true,
        openSessionAnalysisSetup: true,
        closeSessionAnalysisSetup: true,
        toggleSessionAnalysis: true,
        toggleDataWarehouseSource: (source: WarehouseBackedSource) => ({ source }),
        initiateDataWarehouseSourceToggle: (source: WarehouseBackedSource) => ({ source }),
        openDataSourceSetup: (source: WarehouseBackedSource) => ({ source }),
        closeDataSourceSetup: true,
        onDataSourceSetupComplete: (source: WarehouseBackedSource) => ({ source }),
        toggleSignalSource: (params: ToggleSignalSourceParams) => ({ params }),
        toggleSignalSourceSuccess: (params: ToggleSignalSourceParams) => ({ params }),
        toggleSignalSourceFailure: (params: ToggleSignalSourceParams, error: string) => ({ params, error }),
        toggleErrorTracking: true,
        toggleErrorTrackingComplete: true,
        toggleHealthChecks: true,
        toggleEvalReports: true,
        toggleConversations: true,
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
        dataSourceSetupSource: [
            null as WarehouseBackedSource | null,
            {
                openDataSourceSetup: (_, { source }) => source,
                closeDataSourceSetup: () => null,
                closeSourcesModal: () => null,
            },
        ],
        sourceConfigs: {
            toggleSessionAnalysis: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(
                    state,
                    SignalSourceProduct.SessionReplay,
                    SignalSourceType.SessionAnalysisCluster
                ),
            toggleDataWarehouseSource: (state: SignalSourceConfig[] | null, { source }) => {
                const { sourceProduct, sourceType } = WAREHOUSE_SOURCE_SETUP[source]
                return toggleSourceConfigState(state, sourceProduct, sourceType)
            },
            toggleHealthChecks: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(state, SignalSourceProduct.HealthChecks, SignalSourceType.HealthIssue),
            toggleEvalReports: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(state, SignalSourceProduct.LlmAnalytics, SignalSourceType.EvaluationReport),
            toggleConversations: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(state, SignalSourceProduct.Conversations, SignalSourceType.Ticket),
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
                        c.source_product === SignalSourceProduct.SessionReplay &&
                        c.source_type === SignalSourceType.SessionAnalysisCluster
                ) ?? null,
        ],
        githubIssuesConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) => c.source_product === SignalSourceProduct.Github && c.source_type === SignalSourceType.Issue
                ) ?? null,
        ],
        linearIssuesConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) => c.source_product === SignalSourceProduct.Linear && c.source_type === SignalSourceType.Issue
                ) ?? null,
        ],
        zendeskTicketsConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) => c.source_product === SignalSourceProduct.Zendesk && c.source_type === SignalSourceType.Ticket
                ) ?? null,
        ],
        pgAnalyzeIssuesConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.Pganalyze && c.source_type === SignalSourceType.Issue
                ) ?? null,
        ],
        conversationsConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.Conversations &&
                        c.source_type === SignalSourceType.Ticket
                ) ?? null,
        ],
        isSessionAnalysisToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean =>
                keys.has(`${SignalSourceProduct.SessionReplay}_${SignalSourceType.SessionAnalysisCluster}`),
        ],
        isConversationsToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.Conversations}_${SignalSourceType.Ticket}`),
        ],
        isGithubIssuesToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.Github}_${SignalSourceType.Issue}`),
        ],
        isLinearIssuesToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.Linear}_${SignalSourceType.Issue}`),
        ],
        isZendeskTicketsToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.Zendesk}_${SignalSourceType.Ticket}`),
        ],
        isPgAnalyzeIssuesToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has(`${SignalSourceProduct.Pganalyze}_${SignalSourceType.Issue}`),
        ],
        isErrorTrackingToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has('error_tracking'),
        ],
        healthChecksConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.HealthChecks &&
                        c.source_type === SignalSourceType.HealthIssue
                ) ?? null,
        ],
        isHealthChecksToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean =>
                keys.has(`${SignalSourceProduct.HealthChecks}_${SignalSourceType.HealthIssue}`),
        ],
        evalReportsConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.LlmAnalytics &&
                        c.source_type === SignalSourceType.EvaluationReport
                ) ?? null,
        ],
        isEvalReportsToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean =>
                keys.has(`${SignalSourceProduct.LlmAnalytics}_${SignalSourceType.EvaluationReport}`),
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
                            row.source_product === SignalSourceProduct.ErrorTracking && row.source_type === sourceType
                    )
                    return c?.enabled === true
                })
            },
        ],
        isSessionAnalysisRunning: [
            (s) => [s.sessionAnalysisConfig],
            (config: SignalSourceConfig | null): boolean => config?.status === SignalSourceConfigStatus.RUNNING,
        ],
        enabledSourcesCount: [
            (s) => [s.sourceConfigs],
            // The scout gate is a meta-toggle surfaced in the Scout troop section, not a generic
            // signal source — exclude it so a scout-only project doesn't show the "Signal sources"
            // setup card as done with a phantom "1 watching".
            (sourceConfigs: SignalSourceConfig[] | null): number =>
                sourceConfigs?.filter(
                    (c) =>
                        c.enabled &&
                        !(
                            c.source_product === SignalSourceProduct.SignalsScout &&
                            c.source_type === SignalSourceType.CrossSourceIssue
                        )
                ).length ?? 0,
        ],
        hasNoSources: [
            (s) => [s.sourceConfigs, s.enabledSourcesCount],
            (sourceConfigs: SignalSourceConfig[] | null, enabledSourcesCount: number): boolean =>
                sourceConfigs !== null && enabledSourcesCount === 0,
        ],
    }),

    listeners(({ actions, values }) => {
        // If the required tables for a signal source are not yet syncing on the existing DW source,
        // enable them so the signals workflow has data to process.
        async function ensureRequiredTableSyncing(dwSourceType: string, tableName: string): Promise<void> {
            const source = values.dataWarehouseSources?.results?.find(
                (s: ExternalDataSource) => s.source_type === dwSourceType
            )
            if (!source) {
                return
            }
            await Promise.all(
                schemasToEnableFor(source, tableName).map((schema: ExternalDataSourceSchema) =>
                    api.externalDataSchemas.update(schema.id, { should_sync: true })
                )
            )
        }

        return {
            openSourcesModal: () => {
                // Load external data sources so we can check connectivity when user toggles a source
                actions.loadSources()
            },
            initiateDataWarehouseSourceToggle: async ({ source }) => {
                const { dwSourceType, requiredTables, enableErrorMessage } = WAREHOUSE_SOURCE_SETUP[source]
                const sourceConfig = getWarehouseSourceConfig(values.sourceConfigs, source)
                const isCurrentlyEnabled = sourceConfig?.enabled === true
                if (!isCurrentlyEnabled) {
                    const hasSource =
                        values.dataWarehouseSources?.results?.some(
                            (s: ExternalDataSource) => s.source_type === dwSourceType
                        ) ?? false
                    if (!hasSource) {
                        actions.openDataSourceSetup(source)
                        return
                    }
                    try {
                        await Promise.all(
                            requiredTables.map((table) => ensureRequiredTableSyncing(dwSourceType, table))
                        )
                    } catch (error: any) {
                        lemonToast.error(error?.detail || error?.message || enableErrorMessage)
                        return
                    }
                }
                actions.toggleDataWarehouseSource(source)
            },
            onDataSourceSetupComplete: ({ source }) => {
                actions.closeDataSourceSetup()
                const { sourceProduct, sourceType } = WAREHOUSE_SOURCE_SETUP[source]
                actions.toggleSignalSource({ sourceProduct, sourceType, enabled: true, viaSetupWizard: true })
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
                    // Only a successful enable counts as a connection. First-time when there was no
                    // persisted (non-placeholder) config for this product/type before the toggle.
                    if (enabled) {
                        captureSignalSourceConnected({
                            sourceProduct,
                            sourceType,
                            isFirstConnection: !(existing && !existing.id.startsWith('new_')),
                            viaSetupWizard: params.viaSetupWizard ?? false,
                        })
                    }
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
                // First connection when no persisted error-tracking config existed before this enable.
                const wasConnected = configs.some(
                    (c) => c.source_product === SignalSourceProduct.ErrorTracking && !c.id.startsWith('new_')
                )
                try {
                    for (const sourceType of ERROR_TRACKING_SIGNAL_SOURCE_TYPES) {
                        const existing = configs.find(
                            (c) =>
                                c.source_product === SignalSourceProduct.ErrorTracking && c.source_type === sourceType
                        )
                        if (existing && !existing.id.startsWith('new_')) {
                            await api.signalSourceConfigs.update(existing.id, { enabled: desiredEnabled })
                        } else if (desiredEnabled) {
                            await api.signalSourceConfigs.create({
                                source_product: SignalSourceProduct.ErrorTracking,
                                source_type: sourceType,
                                enabled: true,
                                config: {},
                            })
                        }
                    }
                    breakpoint()
                    actions.toggleErrorTrackingComplete()
                    if (desiredEnabled) {
                        captureSignalSourceConnected({
                            sourceProduct: SignalSourceProduct.ErrorTracking,
                            sourceType: SignalSourceType.IssueCreated,
                            isFirstConnection: !wasConnected,
                            viaSetupWizard: false,
                        })
                    }
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
                    sourceProduct: SignalSourceProduct.SessionReplay,
                    sourceType: SignalSourceType.SessionAnalysisCluster,
                    enabled: desiredEnabled,
                })
            },
            toggleHealthChecks: () => {
                // The optimistic reducer flips the config before this listener runs,
                // so config.enabled already reflects the desired state.
                const config = values.healthChecksConfig
                const desiredEnabled = config?.enabled ?? true
                actions.toggleSignalSource({
                    sourceProduct: SignalSourceProduct.HealthChecks,
                    sourceType: SignalSourceType.HealthIssue,
                    enabled: desiredEnabled,
                })
            },
            toggleEvalReports: () => {
                // The optimistic reducer flips the config before this listener runs,
                // so config.enabled already reflects the desired state.
                const config = values.evalReportsConfig
                const desiredEnabled = config?.enabled ?? true
                actions.toggleSignalSource({
                    sourceProduct: SignalSourceProduct.LlmAnalytics,
                    sourceType: SignalSourceType.EvaluationReport,
                    enabled: desiredEnabled,
                })
            },
            toggleConversations: () => {
                const config = values.conversationsConfig
                // Send the flipped target state. A missing config row means "off", so first toggle enables.
                const desiredEnabled = !(config?.enabled ?? false)
                actions.toggleSignalSource({
                    sourceProduct: SignalSourceProduct.Conversations,
                    sourceType: SignalSourceType.Ticket,
                    enabled: desiredEnabled,
                })
            },
            toggleDataWarehouseSource: ({ source }) => {
                const { sourceProduct, sourceType } = WAREHOUSE_SOURCE_SETUP[source]
                const config = getWarehouseSourceConfig(values.sourceConfigs, source)
                actions.toggleSignalSource({
                    sourceProduct,
                    sourceType,
                    enabled: config?.enabled ?? true,
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
                            source_product: SignalSourceProduct.SessionReplay,
                            source_type: SignalSourceType.SessionAnalysisCluster,
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
                            `new_${SignalSourceProduct.SessionReplay}_${SignalSourceType.SessionAnalysisCluster}`
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

    events(({ actions, values }) => ({
        afterMount: () => {
            if (values.featureFlags[FEATURE_FLAGS.PRODUCT_AUTONOMY]) {
                // The condition allows us to safely mount this logic for user without the product autonomy feature flag
                // without needlessly loading the source configs
                actions.loadSourceConfigs()
            }
        },
    })),
])
