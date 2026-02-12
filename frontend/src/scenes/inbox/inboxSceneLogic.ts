import { actions, events, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { inboxSceneLogicType } from './inboxSceneLogicType'
import { SignalReport, SignalReportArtefact, SignalReportArtefactResponse } from './types'

export const inboxSceneLogic = kea<inboxSceneLogicType>([
    path(['scenes', 'inbox', 'inboxSceneLogic']),

    actions({
        setExpandedReportId: (id: string | null) => ({ id }),
        runSessionAnalysis: true,
        runSessionAnalysisSuccess: true,
        runSessionAnalysisFailure: (error: string) => ({ error }),
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
    }),

    listeners(({ actions }) => ({
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
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadReports()
        },
    })),
])
