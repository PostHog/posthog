import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'
import { range } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { teamLogic } from '../../teamLogic'
import { DataManagementTab } from '../DataManagementScene'
import type { ingestionWarningsLogicType } from './ingestionWarningsLogicType'

export interface IngestionWarningSummary {
    type: string
    lastSeen: string
    count: number
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
        values: [teamLogic, ['currentTeamId', 'timezone']],
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
                        key: Scene.DataManagement,
                        name: `Data management`,
                        path: urls.eventDefinitions(),
                    },
                    {
                        key: DataManagementTab.IngestionWarnings,
                        name: 'Ingestion warnings',
                        path: urls.ingestionWarnings(),
                    },
                ]
            },
        ],
        dates: [
            () => [],
            () => {
                return range(0, 30)
                    .map((i) => dayjs().subtract(i, 'days').format('D MMM YYYY'))
                    .reverse()
            },
        ],
        summaryDatasets: [
            (s) => [s.data, s.timezone],
            (data: IngestionWarningSummary[], timezone: string): Record<string, number[]> => {
                const summaryDatasets: Record<string, number[]> = {}
                data.forEach((summary) => {
                    const result = new Array(30).fill(0)
                    for (const warning of summary.warnings) {
                        const date = dayjsUtcToTimezone(warning.timestamp, timezone)
                        const dayIndex = dayjs().diff(date, 'days')
                        result[dayIndex] += 1
                    }
                    summaryDatasets[summary.type] = result.reverse()
                })
                return summaryDatasets
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadData()
    }),
])
