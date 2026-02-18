import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

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
        setExpandedReportId: (id: string | null) => ({ id }),
        runSessionAnalysis: true,
        runSessionAnalysisSuccess: true,
        runSessionAnalysisFailure: (error: string) => ({ error }),
        toggleSetupMode: true,
        saveSessionAnalysisFilters: (filters: RecordingUniversalFilters) => ({ filters }),
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
            [] as SignalSourceConfig[],
            {
                loadSourceConfigs: async () => {
                    const response = await api.signalSourceConfigs.list()
                    return response.results
                },
            },
        ],
    })),

    reducers({
        expandedReportId: [
            null as string | null,
            {
                setExpandedReportId: (_, { id }) => id,
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
        setupMode: [
            false,
            {
                toggleSetupMode: (state) => !state,
                saveSessionAnalysisFiltersSuccess: () => false,
            },
        ],
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
        sessionAnalysisConfig: [
            (s) => [s.sourceConfigs],
            (sourceConfigs: SignalSourceConfig[]): SignalSourceConfig | null =>
                sourceConfigs.find((c) => c.source_type === SignalSourceType.SESSION_ANALYSIS) ?? null,
        ],
        hasSessionAnalysisSource: [
            (s) => [s.sessionAnalysisConfig],
            (config: SignalSourceConfig | null): boolean => !!config?.enabled,
        ],
    }),

    listeners(({ actions, values }) => ({
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
            } catch (error: any) {
                const errorMessage = error?.detail || error?.message || 'Failed to save filters'
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
])
