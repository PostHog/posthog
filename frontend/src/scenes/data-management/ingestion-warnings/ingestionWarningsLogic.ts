import { kea, connect, path, selectors, events } from 'kea'
import { loaders } from 'kea-loaders'
import { Breadcrumb } from '~/types'
import { urls } from 'scenes/urls'
import api from 'lib/api'

import type { ingestionWarningsLogicType } from './ingestionWarningsLogicType'
import { teamLogic } from '../../teamLogic'

export interface IngestionWarningSummary {
    type: string
    lastSeen: string
    warnings: IngestionWarning[]
}

export interface IngestionWarning {
    type: string
    timestamp: string
    details: Record<string, any>
}

export const ingestionWarningsLogic = kea<ingestionWarningsLogicType>([
    path(['scenes', 'data-management', 'ingestion-warnings', 'ingestionWarningsLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    loaders(({ values }) => ({
        data: [
            [] as IngestionWarningSummary[],
            {
                loadData: async () => {
                    const { results } = await api.get(`api/projects/${values.currentTeamId}/ingestion_warnings`)
                    return results
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        name: `Data Management`,
                        path: urls.eventDefinitions(),
                    },
                    {
                        name: 'Ingestion Warnings',
                        path: urls.ingestionWarnings(),
                    },
                ]
            },
        ],
    }),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadData()
        },
    })),
])
