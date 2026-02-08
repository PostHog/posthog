import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import type { inboxSceneLogicType } from './inboxSceneLogicType'
import { SignalReport, SignalReportArtefact, SignalReportArtefactResponse, SignalReportDebugResponse } from './types'

export const inboxSceneLogic = kea<inboxSceneLogicType>([
    path(['scenes', 'inbox', 'inboxSceneLogic']),

    connect({
        values: [userLogic, ['user'], preflightLogic, ['isDev']],
    }),

    actions({
        setExpandedReportId: (id: string | null) => ({ id }),
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
        debugData: [
            {} as Record<string, SignalReportDebugResponse>,
            {
                loadDebugData: async ({ reportId }: { reportId: string }) => {
                    try {
                        const response = await api.signalReports.debug(reportId)
                        return { ...values.debugData, [reportId]: response }
                    } catch {
                        // 403 for non-staff users - silently ignore
                        return values.debugData
                    }
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
        reportsError: [
            false,
            {
                loadReports: () => false,
                loadReportsFailure: () => true,
            },
        ],
    }),

    selectors({
        showDebugInfo: [
            (s) => [s.user, s.isDev],
            (user, isDev): boolean => {
                return !!(user?.is_staff || user?.is_impersonated || isDev)
            },
        ],
    }),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadReports()
        },
    })),
])
