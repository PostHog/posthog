import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { cohortCalculationHistorySceneLogicType } from './cohortCalculationHistorySceneLogicType'

export interface CohortCalculationHistorySceneLogicProps {
    cohortId: number
}

export interface CohortCalculationHistoryRecord {
    id: number
    team: number
    cohort: number
    filters: any
    count: number | null
    started_at: string
    finished_at: string | null
    queries: Array<{
        query: string
        query_id: string
        query_ms: number
        memory_mb: number
        read_rows: number
        written_rows: number
    }>
    error: string | null
    total_query_ms: number
    total_memory_mb: number
    total_read_rows: number
    total_written_rows: number
    main_query: any
}

export interface CohortCalculationHistoryResponse {
    results: CohortCalculationHistoryRecord[]
    count: number
    next: string | null
    previous: string | null
}

export const cohortCalculationHistorySceneLogic = kea<cohortCalculationHistorySceneLogicType>([
    props({} as CohortCalculationHistorySceneLogicProps),
    key(({ cohortId }) => String(cohortId)),
    path((key) => ['scenes', 'cohorts', 'cohortCalculationHistorySceneLogic', key]),

    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),

    actions({
        setPage: (page: number) => ({ page }),
        setLimit: (limit: number) => ({ limit }),
        setCohortMissing: true,
    }),

    loaders(({ props, actions, values }) => ({
        calculationHistoryResponse: [
            { results: [], count: 0, next: null, previous: null } as CohortCalculationHistoryResponse,
            {
                loadCalculationHistory: async (_, breakpoint) => {
                    if (!props.cohortId || props.cohortId <= 0) {
                        return { results: [], count: 0, next: null, previous: null }
                    }
                    breakpoint()
                    try {
                        const offset = (values.page - 1) * values.limit
                        const response = await api.get(
                            `api/cohort/${props.cohortId}/calculation_history/?limit=${values.limit}&offset=${offset}`
                        )
                        return response
                    } catch (error: any) {
                        if (error.status === 404) {
                            actions.setCohortMissing()
                        }
                        throw error
                    }
                },
            },
        ],
        cohort: [
            null as any,
            {
                loadCohort: async (_, breakpoint) => {
                    if (!props.cohortId || props.cohortId <= 0) {
                        return null
                    }
                    breakpoint()
                    try {
                        return await api.cohorts.get(props.cohortId)
                    } catch {
                        actions.setCohortMissing()
                        return null
                    }
                },
            },
        ],
    })),

    reducers({
        page: [
            1,
            {
                setPage: (_, { page }) => page,
            },
        ],
        limit: [
            100,
            {
                setLimit: (_, { limit }) => limit,
            },
        ],
        cohortMissing: [
            false,
            {
                setCohortMissing: () => true,
            },
        ],
    }),

    listeners(({ actions }) => ({
        setPage: () => {
            actions.loadCalculationHistory({})
        },
        setLimit: () => {
            actions.loadCalculationHistory({})
        },
    })),

    selectors({
        calculationHistory: [
            (s) => [s.calculationHistoryResponse],
            (response: CohortCalculationHistoryResponse): CohortCalculationHistoryRecord[] => response.results,
        ],
        totalRecords: [
            (s) => [s.calculationHistoryResponse],
            (response: CohortCalculationHistoryResponse): number => response.count,
        ],
        hasCalculationHistoryAccess: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.COHORT_CALCULATION_HISTORY],
        ],
    }),

    events(({ actions, props }) => ({
        afterMount: () => {
            if (props.cohortId && props.cohortId > 0) {
                actions.loadCalculationHistory({})
                actions.loadCohort({})
            }
        },
    })),
])
