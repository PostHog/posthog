import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'
import { range } from 'lib/utils'
import { projectLogic } from 'scenes/projectLogic'
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
    // count and day date pairs
    sparkline: [number, string][]
}

export interface IngestionWarning {
    type: string
    timestamp: string
    details: Record<string, any>
}

export const ingestionWarningsLogic = kea<ingestionWarningsLogicType>([
    path(['scenes', 'data-management', 'ingestion-warnings', 'ingestionWarningsLogic']),

    connect(() => ({
        values: [teamLogic, ['timezone'], projectLogic, ['currentProjectId']],
    })),

    actions({
        setSearchQuery: (search: string) => ({ search }),
    }),

    reducers({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { search }) => search,
            },
        ],
    }),

    loaders(({ values }) => ({
        data: [
            [] as IngestionWarningSummary[],
            {
                loadData: async () => {
                    const q = values.searchQuery ? `?q=${values.searchQuery}` : ''
                    const { results } = await api.get(`api/projects/${values.currentProjectId}/ingestion_warnings${q}`)
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
                        iconType: 'event_definition',
                    },
                    {
                        key: DataManagementTab.IngestionWarnings,
                        name: 'Ingestion warnings',
                        path: urls.ingestionWarnings(),
                        iconType: 'ingestion_warning',
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
                    for (const spark of summary.sparkline) {
                        const date = dayjsUtcToTimezone(spark[1], timezone)
                        const dayIndex = dayjs().diff(date, 'days')
                        result[dayIndex] = spark[0]
                    }
                    summaryDatasets[summary.type] = result.reverse()
                })
                return summaryDatasets
            },
        ],
        showProductIntro: [
            (s) => [s.data, s.dataLoading, s.searchQuery],
            (data: IngestionWarningSummary[], dataLoading: boolean, searchQuery) =>
                data.length === 0 && !dataLoading && !searchQuery.trim().length,
        ],
    }),

    listeners(({ actions }) => ({
        setSearchQuery: async (_, breakpoint) => {
            await breakpoint(100)
            actions.loadData()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadData()
    }),
])
