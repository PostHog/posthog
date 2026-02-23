import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { RecordingUniversalFilters } from '~/types'

import type { signalSourcesLogicType } from './signalSourcesLogicType'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from './types'

export const signalSourcesLogic = kea<signalSourcesLogicType>([
    path(['scenes', 'inbox', 'signalSourcesLogic']),

    actions({
        openSourcesModal: true,
        closeSourcesModal: true,
        openSessionAnalysisSetup: true,
        closeSessionAnalysisSetup: true,
        toggleSessionAnalysis: true,
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
        toggleSessionAnalysis: async (_, breakpoint) => {
            const config = values.sessionAnalysisConfig
            const desiredEnabled = config?.enabled ?? true
            try {
                if (
                    config &&
                    config.id !==
                        `new_${SignalSourceProduct.SESSION_REPLAY}_${SignalSourceType.SESSION_ANALYSIS_CLUSTER}`
                ) {
                    await api.signalSourceConfigs.update(config.id, { enabled: desiredEnabled })
                } else {
                    await api.signalSourceConfigs.create({
                        source_product: SignalSourceProduct.SESSION_REPLAY,
                        source_type: SignalSourceType.SESSION_ANALYSIS_CLUSTER,
                        config: {},
                        enabled: true,
                    })
                }
                breakpoint()
                actions.loadSourceConfigs()
            } catch (error: any) {
                breakpoint()
                actions.loadSourceConfigs()
                const errorMessage = error?.detail || error?.message || 'Failed to toggle session analysis'
                lemonToast.error(errorMessage)
            }
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
            actions.loadSourceConfigs()
        },
    })),
])
