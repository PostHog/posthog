import { MakeLogicType, actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SignalSourceProduct, SignalSourceType } from 'scenes/inbox/types'
import { teamLogic } from 'scenes/teamLogic'

import { ExternalDataSourceType } from '~/queries/schema/schema-general'
import { ExternalDataSource, ExternalDataSourceSchema, RecordingUniversalFilters } from '~/types'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'
import {
    engineeringAnalyticsCiSignalsConfigRetrieve,
    engineeringAnalyticsCiSignalsConfigUpdate,
} from 'products/engineering_analytics/frontend/generated/api'
import type { CISignalsConfigApi } from 'products/engineering_analytics/frontend/generated/api.schemas'

import type { PaginatedResponse } from '../../lib/api'
import type { FeatureFlagsSet } from '../../lib/logic/featureFlagLogic'
import { captureSignalSourceConnected } from './inboxAnalytics'
import { SignalSourceConfig, SignalSourceConfigStatus, ToggleSignalSourceParams } from './types'

/** Matches Cymbal `EmitSignalRequest.source_type` + `products.signals.backend.api.emit_signal` checks. */
export const ERROR_TRACKING_SIGNAL_SOURCE_TYPES: SignalSourceType[] = [
    SignalSourceType.IssueCreated,
    SignalSourceType.IssueReopened,
    SignalSourceType.IssueSpiking,
]

/** Warehouse-backed signal sources, keyed by roster source id. */
export type WarehouseBackedSource = 'github' | 'linear' | 'zendesk' | 'pganalyze' | 'engineering_analytics'

type WarehouseSourceCompletion =
    | {
          kind: 'source_config'
          sourceProduct: SignalSourceProduct
          sourceType: SignalSourceType
          enableErrorMessage: string
      }
    | { kind: 'ci_signals_bundle' }

/**
 * One registration per warehouse-backed signal source: the warehouse product that backs it, the
 * tables its signals read (pre-selected in the wizard and forced to sync), and what enabling means
 * once connected. Keyed by signal source, not warehouse product — GitHub backs more than one source.
 */
export const WAREHOUSE_SOURCE_SETUP: Record<
    WarehouseBackedSource,
    {
        dwSourceType: ExternalDataSourceType
        requiredTables: string[]
        completion: WarehouseSourceCompletion
    }
> = {
    github: {
        dwSourceType: 'Github',
        requiredTables: ['issues'],
        completion: {
            kind: 'source_config',
            sourceProduct: SignalSourceProduct.Github,
            sourceType: SignalSourceType.Issue,
            enableErrorMessage: 'Failed to enable GitHub Issues',
        },
    },
    linear: {
        dwSourceType: 'Linear',
        requiredTables: ['issues'],
        completion: {
            kind: 'source_config',
            sourceProduct: SignalSourceProduct.Linear,
            sourceType: SignalSourceType.Issue,
            enableErrorMessage: 'Failed to enable Linear Issues',
        },
    },
    zendesk: {
        dwSourceType: 'Zendesk',
        requiredTables: ['tickets'],
        completion: {
            kind: 'source_config',
            sourceProduct: SignalSourceProduct.Zendesk,
            sourceType: SignalSourceType.Ticket,
            enableErrorMessage: 'Failed to enable Zendesk Tickets',
        },
    },
    pganalyze: {
        dwSourceType: 'PgAnalyze',
        requiredTables: ['issues', 'servers'],
        completion: {
            kind: 'source_config',
            sourceProduct: SignalSourceProduct.Pganalyze,
            sourceType: SignalSourceType.Issue,
            enableErrorMessage: 'Failed to enable pganalyze',
        },
    },
    engineering_analytics: {
        dwSourceType: 'Github',
        requiredTables: ['workflow_runs', 'pull_requests', 'workflow_jobs'],
        completion: { kind: 'ci_signals_bundle' },
    },
}

/** Values subset used by data-warehouse source helpers */
interface SignalSourcesLogicValuesForDw {
    sourceConfigs: SignalSourceConfig[] | null
}

function getWarehouseSourceConfig(
    values: SignalSourcesLogicValuesForDw,
    source: WarehouseBackedSource
): SignalSourceConfig | null {
    const { completion } = WAREHOUSE_SOURCE_SETUP[source]
    if (completion.kind !== 'source_config') {
        return null
    }
    return (
        values.sourceConfigs?.find(
            (c) => c.source_product === completion.sourceProduct && c.source_type === completion.sourceType
        ) ?? null
    )
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

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface signalSourcesLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null // sourcesDataLogic
    dataWarehouseSourcesLoading: boolean // sourcesDataLogic
    anomalyInvestigationConfig: SignalSourceConfig | null
    ciSignalsConfig: CISignalsConfigApi | null
    ciSignalsConfigLoading: boolean
    ciSignalsIsFullyEnabled: boolean
    conversationsConfig: SignalSourceConfig | null
    dataSourceSetupSource: WarehouseBackedSource | null
    enabledSourcesCount: number
    errorTrackingIsFullyEnabled: boolean
    evalReportsConfig: SignalSourceConfig | null
    githubIssuesConfig: SignalSourceConfig | null
    hasNoSources: boolean
    healthChecksConfig: SignalSourceConfig | null
    isAnomalyInvestigationToggling: boolean
    isCiSignalsToggling: boolean
    isConversationsToggling: boolean
    isErrorTrackingToggling: boolean
    isEvalReportsToggling: boolean
    isGithubIssuesToggling: boolean
    isHealthChecksToggling: boolean
    isLinearIssuesToggling: boolean
    isPgAnalyzeIssuesToggling: boolean
    isSessionAnalysisRunning: boolean
    isSessionAnalysisToggling: boolean
    isZendeskTicketsToggling: boolean
    linearIssuesConfig: SignalSourceConfig | null
    pgAnalyzeIssuesConfig: SignalSourceConfig | null
    sessionAnalysisConfig: SignalSourceConfig | null
    sessionAnalysisSetupOpen: boolean
    sourceConfigs: SignalSourceConfig[] | null
    sourceConfigsLoading: boolean
    sourcesModalOpen: boolean
    togglingSourceKeys: Set<string>
    zendeskTicketsConfig: SignalSourceConfig | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface signalSourcesLogicActions {
    loadSources: () => {
        value: true
    } // sourcesDataLogic
    clearSessionAnalysisFilters: () => {
        value: true
    }
    closeDataSourceSetup: () => {
        value: true
    }
    closeSessionAnalysisSetup: () => {
        value: true
    }
    closeSourcesModal: () => {
        value: true
    }
    initiateDataWarehouseSourceToggle: (source: WarehouseBackedSource) => {
        source: WarehouseBackedSource
    }
    loadCiSignalsConfig: () => any
    loadCiSignalsConfigFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCiSignalsConfigSuccess: (
        ciSignalsConfig: CISignalsConfigApi,
        payload?: any
    ) => {
        ciSignalsConfig: CISignalsConfigApi
        payload?: any
    }
    loadSourceConfigs: () => any
    loadSourceConfigsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSourceConfigsSuccess: (
        sourceConfigs: SignalSourceConfig[],
        payload?: any
    ) => {
        sourceConfigs: SignalSourceConfig[]
        payload?: any
    }
    onDataSourceSetupComplete: () => {
        value: true
    }
    openDataSourceSetup: (source: WarehouseBackedSource) => {
        source: WarehouseBackedSource
    }
    openSessionAnalysisSetup: () => {
        value: true
    }
    openSourcesModal: () => {
        value: true
    }
    saveSessionAnalysisFilters: (filters: RecordingUniversalFilters) => {
        filters: RecordingUniversalFilters
    }
    toggleAnomalyInvestigation: () => {
        value: true
    }
    toggleCiSignals: (viaSetupWizard?: boolean) => {
        viaSetupWizard: boolean
    }
    toggleCiSignalsComplete: () => {
        value: true
    }
    toggleConversations: () => {
        value: true
    }
    toggleDataWarehouseSource: (source: WarehouseBackedSource) => {
        source: WarehouseBackedSource
    }
    toggleErrorTracking: () => {
        value: true
    }
    toggleErrorTrackingComplete: () => {
        value: true
    }
    toggleEvalReports: () => {
        value: true
    }
    toggleHealthChecks: () => {
        value: true
    }
    toggleSessionAnalysis: () => {
        value: true
    }
    toggleSignalSource: (params: ToggleSignalSourceParams) => {
        params: ToggleSignalSourceParams
    }
    toggleSignalSourceFailure: (
        params: ToggleSignalSourceParams,
        error: string
    ) => {
        error: string
        params: ToggleSignalSourceParams
    }
    toggleSignalSourceSuccess: (params: ToggleSignalSourceParams) => {
        params: ToggleSignalSourceParams
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface signalSourcesLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        sessionAnalysisConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        githubIssuesConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        linearIssuesConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        zendeskTicketsConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        pgAnalyzeIssuesConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        conversationsConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        isSessionAnalysisToggling: (togglingSourceKeys: Set<string>) => boolean
        isConversationsToggling: (togglingSourceKeys: Set<string>) => boolean
        isGithubIssuesToggling: (togglingSourceKeys: Set<string>) => boolean
        isLinearIssuesToggling: (togglingSourceKeys: Set<string>) => boolean
        isZendeskTicketsToggling: (togglingSourceKeys: Set<string>) => boolean
        isPgAnalyzeIssuesToggling: (togglingSourceKeys: Set<string>) => boolean
        isErrorTrackingToggling: (togglingSourceKeys: Set<string>) => boolean
        healthChecksConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        isHealthChecksToggling: (togglingSourceKeys: Set<string>) => boolean
        evalReportsConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        isEvalReportsToggling: (togglingSourceKeys: Set<string>) => boolean
        anomalyInvestigationConfig: (sourceConfigs: SignalSourceConfig[] | null) => SignalSourceConfig | null
        isAnomalyInvestigationToggling: (togglingSourceKeys: Set<string>) => boolean
        errorTrackingIsFullyEnabled: (sourceConfigs: SignalSourceConfig[] | null) => boolean
        ciSignalsIsFullyEnabled: (ciSignalsConfig: CISignalsConfigApi | null) => boolean
        isCiSignalsToggling: (togglingSourceKeys: Set<string>) => boolean
        isSessionAnalysisRunning: (sessionAnalysisConfig: SignalSourceConfig | null) => boolean
        enabledSourcesCount: (sourceConfigs: SignalSourceConfig[] | null) => number
        hasNoSources: (sourceConfigs: SignalSourceConfig[] | null, enabledSourcesCount: number) => boolean
    }
}

export type signalSourcesLogicType = MakeLogicType<
    signalSourcesLogicValues,
    signalSourcesLogicActions,
    Record<string, any>,
    signalSourcesLogicMeta
>

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
        onDataSourceSetupComplete: true,
        toggleSignalSource: (params: ToggleSignalSourceParams) => ({ params }),
        toggleSignalSourceSuccess: (params: ToggleSignalSourceParams) => ({ params }),
        toggleSignalSourceFailure: (params: ToggleSignalSourceParams, error: string) => ({ params, error }),
        toggleErrorTracking: true,
        toggleErrorTrackingComplete: true,
        toggleCiSignals: (viaSetupWizard?: boolean) => ({ viaSetupWizard: viaSetupWizard ?? false }),
        toggleCiSignalsComplete: true,
        toggleHealthChecks: true,
        toggleEvalReports: true,
        toggleConversations: true,
        toggleAnomalyInvestigation: true,
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
        ciSignalsConfig: [
            null as CISignalsConfigApi | null,
            {
                loadCiSignalsConfig: async (): Promise<CISignalsConfigApi> =>
                    engineeringAnalyticsCiSignalsConfigRetrieve(String(teamLogic.values.currentTeamId)),
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
                const { completion } = WAREHOUSE_SOURCE_SETUP[source]
                if (completion.kind !== 'source_config') {
                    return state
                }
                return toggleSourceConfigState(state, completion.sourceProduct, completion.sourceType)
            },
            toggleHealthChecks: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(state, SignalSourceProduct.HealthChecks, SignalSourceType.HealthIssue),
            toggleEvalReports: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(state, SignalSourceProduct.LlmAnalytics, SignalSourceType.EvaluationReport),
            toggleConversations: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(state, SignalSourceProduct.Conversations, SignalSourceType.Ticket),
            toggleAnomalyInvestigation: (state: SignalSourceConfig[] | null) =>
                toggleSourceConfigState(state, SignalSourceProduct.Analytics, SignalSourceType.AnomalyInvestigation),
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
                toggleCiSignals: (state) => {
                    const next = new Set(state)
                    next.add('engineering_analytics')
                    return next
                },
                toggleCiSignalsComplete: (state) => {
                    const next = new Set(state)
                    next.delete('engineering_analytics')
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
        anomalyInvestigationConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.Analytics &&
                        c.source_type === SignalSourceType.AnomalyInvestigation
                ) ?? null,
        ],
        isAnomalyInvestigationToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean =>
                keys.has(`${SignalSourceProduct.Analytics}_${SignalSourceType.AnomalyInvestigation}`),
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
        ciSignalsIsFullyEnabled: [
            (s) => [s.ciSignalsConfig],
            (ciSignalsConfig: CISignalsConfigApi | null): boolean => ciSignalsConfig?.enabled ?? false,
        ],
        isCiSignalsToggling: [
            (s) => [s.togglingSourceKeys],
            (keys: Set<string>): boolean => keys.has('engineering_analytics'),
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
        // If the required table for a signal source is not yet syncing on the existing DW source,
        // enable it so the signals workflow has data to process.
        async function ensureRequiredTableSyncing(dwSourceType: string, tableName: string): Promise<void> {
            const schemas = values.dataWarehouseSources?.results
                ?.filter((source: ExternalDataSource) => source.source_type === dwSourceType)
                .flatMap((source: ExternalDataSource) => source.schemas ?? [])
                .filter((schema: ExternalDataSourceSchema) => schema.name === tableName && !schema.should_sync)
            await Promise.all(
                (schemas ?? []).map((schema: ExternalDataSourceSchema) =>
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
                const { dwSourceType, requiredTables, completion } = WAREHOUSE_SOURCE_SETUP[source]
                const sourceConfig = getWarehouseSourceConfig(values, source)
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
                        for (const table of requiredTables) {
                            await ensureRequiredTableSyncing(dwSourceType, table)
                        }
                    } catch (error: any) {
                        const fallback =
                            completion.kind === 'source_config'
                                ? completion.enableErrorMessage
                                : 'Failed to enable source'
                        lemonToast.error(error?.detail || error?.message || fallback)
                        return
                    }
                }
                actions.toggleDataWarehouseSource(source)
            },
            onDataSourceSetupComplete: () => {
                const source = values.dataSourceSetupSource
                actions.closeDataSourceSetup()
                if (source === null) {
                    return
                }
                const { completion } = WAREHOUSE_SOURCE_SETUP[source]
                if (completion.kind === 'ci_signals_bundle') {
                    actions.toggleCiSignals(true)
                    return
                }
                actions.toggleSignalSource({
                    sourceProduct: completion.sourceProduct,
                    sourceType: completion.sourceType,
                    enabled: true,
                    viaSetupWizard: true,
                })
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
            toggleCiSignals: async ({ viaSetupWizard }, breakpoint) => {
                const desiredEnabled = !values.ciSignalsIsFullyEnabled
                const wasConnected = values.ciSignalsConfig?.configured ?? false
                // The setup wizard just connected GitHub with the CI tables preselected, so both
                // checks below would race the still-refreshing sources list — skip them.
                if (desiredEnabled && !viaSetupWizard) {
                    const hasGithubSource =
                        values.dataWarehouseSources?.results?.some(
                            (s: ExternalDataSource) => s.source_type === 'Github'
                        ) ?? false
                    if (!hasGithubSource) {
                        actions.toggleCiSignalsComplete()
                        actions.openDataSourceSetup('engineering_analytics')
                        return
                    }
                    try {
                        const ciSetup = WAREHOUSE_SOURCE_SETUP.engineering_analytics
                        for (const tableName of ciSetup.requiredTables) {
                            await ensureRequiredTableSyncing(ciSetup.dwSourceType, tableName)
                        }
                    } catch (error: any) {
                        actions.toggleCiSignalsComplete()
                        lemonToast.error(error?.detail || error?.message || 'Failed to enable GitHub CI signals')
                        return
                    }
                }
                try {
                    const updatedConfig = await engineeringAnalyticsCiSignalsConfigUpdate(
                        String(teamLogic.values.currentTeamId),
                        { enabled: desiredEnabled }
                    )
                    breakpoint()
                    actions.loadCiSignalsConfigSuccess(updatedConfig)
                    actions.toggleCiSignalsComplete()
                    if (desiredEnabled) {
                        captureSignalSourceConnected({
                            sourceProduct: SignalSourceProduct.EngineeringAnalytics,
                            sourceType: SignalSourceType.CiFlakyCheck,
                            isFirstConnection: !wasConnected,
                            viaSetupWizard,
                        })
                    }
                    actions.loadSourceConfigs()
                } catch (error: any) {
                    breakpoint() // re-throws if superseded, skipping the lines below
                    actions.toggleCiSignalsComplete()
                    const errorMessage = error?.detail || error?.message || 'Failed to toggle GitHub CI signals'
                    lemonToast.error(errorMessage)
                    actions.loadCiSignalsConfig()
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
                // The optimistic reducer flips the config before this listener runs,
                // so config.enabled already reflects the desired state.
                const config = values.conversationsConfig
                const desiredEnabled = config?.enabled ?? true
                actions.toggleSignalSource({
                    sourceProduct: SignalSourceProduct.Conversations,
                    sourceType: SignalSourceType.Ticket,
                    enabled: desiredEnabled,
                })
            },
            toggleAnomalyInvestigation: () => {
                // The optimistic reducer flips the config before this listener runs,
                // so config.enabled already reflects the desired state.
                const config = values.anomalyInvestigationConfig
                const desiredEnabled = config?.enabled ?? true
                actions.toggleSignalSource({
                    sourceProduct: SignalSourceProduct.Analytics,
                    sourceType: SignalSourceType.AnomalyInvestigation,
                    enabled: desiredEnabled,
                })
            },
            toggleDataWarehouseSource: ({ source }) => {
                const { completion } = WAREHOUSE_SOURCE_SETUP[source]
                if (completion.kind !== 'source_config') {
                    return
                }
                const config = getWarehouseSourceConfig(values, source)
                actions.toggleSignalSource({
                    sourceProduct: completion.sourceProduct,
                    sourceType: completion.sourceType,
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
                if (values.featureFlags[FEATURE_FLAGS.ENGINEERING_ANALYTICS]) {
                    actions.loadCiSignalsConfig()
                }
            }
        },
    })),
])
