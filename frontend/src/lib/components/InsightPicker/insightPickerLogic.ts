import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { Sorting } from 'lib/lemon-ui/LemonTable'
import { toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { QueryBasedInsightModel } from '~/types'

import type { insightPickerLogicType } from './insightPickerLogicType'

const DEFAULT_INSIGHTS_PER_PAGE = 20

export interface InsightPickerLogicProps {
    logicKey: string
    insightsPerPage?: number
}

export const insightPickerLogic = kea<insightPickerLogicType>([
    path((key) => ['lib', 'components', 'InsightPicker', 'insightPickerLogic', key]),
    props({} as InsightPickerLogicProps),
    key((props) => props.logicKey),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        setSearch: (search: string) => ({ search }),
        setPage: (page: number) => ({ page }),
        setInsightType: (insightType: string) => ({ insightType }),
        setSorting: (sorting: Sorting | null) => ({ sorting }),
        resetFilters: true,
    }),
    reducers({
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
                resetFilters: () => '',
            },
        ],
        page: [
            1,
            {
                setPage: (_, { page }) => page,
                setSearch: () => 1,
                setInsightType: () => 1,
                resetFilters: () => 1,
            },
        ],
        insightType: [
            'All types',
            {
                setInsightType: (_, { insightType }) => insightType,
                resetFilters: () => 'All types',
            },
        ],
        sorting: [
            null as Sorting | null,
            {
                setSorting: (_, { sorting }) => sorting,
                resetFilters: () => null,
            },
        ],
    }),
    loaders(({ values, props }) => ({
        insights: {
            __default: { results: [] as QueryBasedInsightModel[], count: 0 },
            loadInsights: async (_, breakpoint) => {
                await breakpoint(300)

                const perPage = props.insightsPerPage ?? DEFAULT_INSIGHTS_PER_PAGE

                const params: Record<string, any> = {
                    limit: perPage,
                    offset: Math.max(0, (values.page - 1) * perPage),
                    saved: true,
                    basic: true,
                }

                if (values.search) {
                    params.search = values.search
                }
                if (values.insightType && values.insightType.toLowerCase() !== 'all types') {
                    params.insight = values.insightType.toUpperCase()
                }
                if (values.sorting) {
                    params.order = `${values.sorting.order === -1 ? '-' : ''}${values.sorting.columnKey}`
                }

                const response = await api.get(
                    `api/environments/${teamLogic.values.currentTeamId}/insights/?${toParams(params)}`
                )

                breakpoint()

                return {
                    ...response,
                    results: response.results.map((rawInsight: any) => getQueryBasedInsightModel(rawInsight)),
                }
            },
        },
    })),
    selectors({
        count: [(s) => [s.insights], (insights) => insights.count],
        insightsPerPage: [
            () => [(_, props) => props.insightsPerPage],
            (insightsPerPage) => insightsPerPage ?? DEFAULT_INSIGHTS_PER_PAGE,
        ],
    }),
    listeners(({ actions }) => ({
        setSearch: () => {
            actions.loadInsights()
        },
        setPage: () => {
            actions.loadInsights()
        },
        setInsightType: () => {
            actions.loadInsights()
        },
        setSorting: () => {
            actions.loadInsights()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadInsights()
    }),
])
