import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { SignalReport, SignalReportArtefact, SignalReportArtefactResponse } from './types'
import type { inboxSceneLogicType } from './inboxSceneLogicType'

export const inboxSceneLogic = kea<inboxSceneLogicType>([
    path(['scenes', 'inbox', 'inboxSceneLogic']),

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
    })),

    reducers({
        expandedReportId: [
            null as string | null,
            {
                setExpandedReportId: (_, { id }) => id,
            },
        ],
    }),
])
