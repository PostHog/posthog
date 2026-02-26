import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'

import { RecordingUniversalFilters } from '~/types'

import type { signalSourcesLogicType } from './signalSourcesLogicType'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType, ToggleSignalSourceParams } from './types'

export const signalSourcesLogic = kea<signalSourcesLogicType>([
    path(['scenes', 'inbox', 'signalSourcesLogic']),

    actions({
        openSourcesModal: true,
        closeSourcesModal: true,
        openSessionAnalysisSetup: true,
        closeSessionAnalysisSetup: true,
        toggleSessionAnalysis: true,
        toggleSignalSource: (params: ToggleSignalSourceParams) => ({ params }),
        toggleSignalSourceSuccess: (params: ToggleSignalSourceParams) => ({ params }),
        toggleSignalSourceFailure: (params: ToggleSignalSourceParams, error: string) => ({ params, error }),
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
        sourceConfigs: {
            toggleSessionAnalysis: (state: SignalSourceConfig[] | null) => {
                if (!state) {
                    return state
                }
                const existing = state.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.SESSION_REPLAY &&
                        c.source_type === SignalSourceType.SESSION_ANALYSIS_CLUSTER
                )
                if (existing) {
                    return state.map((c) =>
                        c.source_product === SignalSourceProduct.SESSION_REPLAY &&
                        c.source_type === SignalSourceType.SESSION_ANALYSIS_CLUSTER
                            ? { ...c, enabled: !c.enabled }
                            : c
                    )
                }
                return [
                    ...state,
                    {
                        id: `new_${SignalSourceProduct.SESSION_REPLAY}_${SignalSourceType.SESSION_ANALYSIS_CLUSTER}`,
                        source_product: SignalSourceProduct.SESSION_REPLAY,
                        source_type: SignalSourceType.SESSION_ANALYSIS_CLUSTER,
                        enabled: true,
                        config: {},
                        created_at: new Date().toISOString(),
                        updated_at: new Date().toISOString(),
                    },
                ]
            },
        },
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

    listeners(({ actions, values }) => ({
        toggleSignalSource: async ({ params }, breakpoint) => {
            const { sourceProduct, sourceType, enabled, config } = params
            try {
                const configs = values.sourceConfigs ?? []
                const existing = configs.find((c) => c.source_product === sourceProduct && c.source_type === sourceType)

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
        toggleSessionAnalysis: () => {
            const config = values.sessionAnalysisConfig
            const desiredEnabled = config?.enabled ?? true
            actions.toggleSignalSource({
                sourceProduct: SignalSourceProduct.SESSION_REPLAY,
                sourceType: SignalSourceType.SESSION_ANALYSIS_CLUSTER,
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
    })),

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
