import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { Breadcrumb, RecordingUniversalFilters } from '~/types'

import type { inboxSceneLogicType } from './inboxSceneLogicType'
import {
    SignalReport,
    SignalReportArtefact,
    SignalReportArtefactResponse,
    SignalSourceConfig,
    SignalSourceType,
} from './types'

export const inboxSceneLogic = kea<inboxSceneLogicType>([
    path(['scenes', 'inbox', 'inboxSceneLogic']),

    actions({
        setSelectedReportId: (id: string | null) => ({ id }),
        setSearchQuery: (query: string) => ({ query }),
        runSessionAnalysis: true,
        runSessionAnalysisSuccess: true,
        runSessionAnalysisFailure: (error: string) => ({ error }),
        openSourcesModal: true,
        closeSourcesModal: true,
        openSessionAnalysisSetup: true,
        closeSessionAnalysisSetup: true,
        toggleSessionAnalysis: true,
        saveSessionAnalysisFilters: (filters: RecordingUniversalFilters) => ({ filters }),
        clearSessionAnalysisFilters: true,
    }),

    loaders(({ values }) => ({
        reports: [
            [] as SignalReport[],
            {
                loadReports: async () => {
                    const response = await api.signalReports.list()
                    return response.results
                },
            },
        ],
        artefacts: [
            {} as Record<string, SignalReportArtefact[]>,
            {
                loadArtefacts: async ({ reportId }: { reportId: string }) => {
                    const response: SignalReportArtefactResponse = await api.signalReports.artefacts(reportId)
                    return { ...values.artefacts, [reportId]: response.results }
                },
            },
        ],
        sourceConfigs: [
            null as SignalSourceConfig[] | null,
            {
                loadSourceConfigs: async () => {
                    const response = await api.signalSourceConfigs.list()
                    return response.results
                },
            },
        ],
    })),

    reducers({
        selectedReportId: [
            null as string | null,
            {
                setSelectedReportId: (_, { id }) => id,
            },
        ],
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { query }) => query,
            },
        ],
        isRunningSessionAnalysis: [
            false,
            {
                runSessionAnalysis: () => true,
                runSessionAnalysisSuccess: () => false,
                runSessionAnalysisFailure: () => false,
            },
        ],
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
                openSourcesModal: () => false, // This reset is on open, and not on close, to avoid flash on modal close
                openSessionAnalysisSetup: () => true,
                closeSessionAnalysisSetup: () => false,
            },
        ],
        sourceConfigs: {
            toggleSessionAnalysis: (state: SignalSourceConfig[] | null) => {
                if (!state) {
                    return state
                }
                const existing = state.find((c) => c.source_type === SignalSourceType.SESSION_ANALYSIS)
                if (existing) {
                    return state.map((c) =>
                        c.source_type === SignalSourceType.SESSION_ANALYSIS ? { ...c, enabled: !c.enabled } : c
                    )
                }
                return [
                    ...state,
                    {
                        id: 'optimistic',
                        source_type: SignalSourceType.SESSION_ANALYSIS,
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
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'inbox',
                    name: sceneConfigurations[Scene.Inbox].name,
                    iconType: 'inbox',
                },
            ],
        ],
        filteredReports: [
            (s) => [s.reports, s.searchQuery],
            (reports: SignalReport[], searchQuery: string): SignalReport[] => {
                if (!searchQuery.trim()) {
                    return reports
                }
                const q = searchQuery.toLowerCase()
                return reports.filter((r) => r.title?.toLowerCase().includes(q) || r.summary?.toLowerCase().includes(q))
            },
        ],
        selectedReport: [
            (s) => [s.reports, s.selectedReportId],
            (reports: SignalReport[], selectedReportId: string | null): SignalReport | null =>
                reports.find((r) => r.id === selectedReportId) ?? null,
        ],
        sessionAnalysisConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): SignalSourceConfig | null =>
                sourceConfigs?.find((c) => c.source_type === SignalSourceType.SESSION_ANALYSIS) ?? null,
        ],
        hasNoSources: [
            (s) => [s.sourceConfigs, s.enabledSourcesCount],
            (sourceConfigs: SignalSourceConfig[] | null, enabledSourcesCount: number): boolean =>
                sourceConfigs !== null && enabledSourcesCount === 0,
        ],
        shouldShowEnablingCtaOnMobile: [
            (s) => [s.hasNoSources, s.filteredReports, s.reportsLoading],
            (hasNoSources, filteredReports, reportsLoading): boolean =>
                hasNoSources && !reportsLoading && filteredReports.length === 0,
        ],
        enabledSourcesCount: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[] | null): number => sourceConfigs?.filter((c) => c.enabled).length ?? 0,
        ],
    }),

    listeners(({ actions, values }) => ({
        setSelectedReportId: ({ id }) => {
            if (id && !values.artefacts[id]) {
                actions.loadArtefacts({ reportId: id })
            }
        },
        runSessionAnalysis: async () => {
            try {
                await api.signalReports.analyzeSessions()
                lemonToast.success('Session analysis completed')
                actions.runSessionAnalysisSuccess()
            } catch (error: any) {
                const errorMessage = error?.detail || error?.message || 'Failed to run session analysis'
                lemonToast.error(errorMessage)
                actions.runSessionAnalysisFailure(errorMessage)
            }
        },
        runSessionAnalysisSuccess: () => {
            actions.loadReports()
        },
        toggleSessionAnalysis: async (_, breakpoint) => {
            // Reducer already applied optimistic update, so read the NEW desired state
            const config = values.sessionAnalysisConfig
            const desiredEnabled = config?.enabled ?? true
            try {
                if (config && config.id !== 'optimistic') {
                    await api.signalSourceConfigs.update(config.id, { enabled: desiredEnabled })
                } else {
                    await api.signalSourceConfigs.create({
                        source_type: SignalSourceType.SESSION_ANALYSIS,
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
                        source_type: SignalSourceType.SESSION_ANALYSIS,
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
                if (existing && existing.id !== 'optimistic') {
                    await api.signalSourceConfigs.update(existing.id, { config: {}, enabled: true })
                }
                lemonToast.success('Session analysis filters cleared')
                actions.loadSourceConfigs()
            } catch (error: any) {
                const errorMessage = error?.detail || error?.message || 'Failed to clear filters'
                lemonToast.error(errorMessage)
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadReports()
            actions.loadSourceConfigs()
        },
    })),

    actionToUrl(({ values }) => ({
        setSelectedReportId: () => [
            values.selectedReportId ? urls.inbox(values.selectedReportId) : urls.inbox(),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
    })),

    urlToAction(({ actions, values }) => ({
        [urls.inbox()]: () => {
            if (values.selectedReportId !== null) {
                actions.setSelectedReportId(null)
            }
        },
        [urls.inbox(':reportId')]: ({ reportId }: { reportId?: string }) => {
            const id = reportId ?? null
            if (values.selectedReportId !== id) {
                actions.setSelectedReportId(id)
            }
        },
    })),
])
