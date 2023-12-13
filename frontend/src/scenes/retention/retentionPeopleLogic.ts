import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { toParams } from 'lib/utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { RetentionTableAppearanceType, RetentionTablePeoplePayload } from 'scenes/retention/types'

import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { query } from '~/queries/query'
import { NodeKind, PersonsQuery, RetentionQuery } from '~/queries/schema'
import { InsightLogicProps } from '~/types'

import type { retentionPeopleLogicType } from './retentionPeopleLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export function wrapRetentionQuery(query: RetentionQuery, selectedInterval: number, offset = 0): PersonsQuery {
    return {
        kind: NodeKind.PersonsQuery,
        select: ['person', 'appearances'],
        orderBy: ['appearances_count DESC', 'actor_id'],
        source: {
            kind: NodeKind.InsightPersonsQuery,
            source: {
                ...query,
                retentionFilter: {
                    ...query.retentionFilter,
                    selected_interval: selectedInterval,
                },
            },
        },
        offset,
    }
}

const hogQLInsightsRetentionFlagEnabled = (): boolean =>
    Boolean(featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.HOGQL_INSIGHTS_RETENTION])

function turnAppearancesTo_1s_0s(
    appearances: number[],
    totalIntervals: number,
    selectedInterval: number | null
): number[] {
    const newTotalIntervals = totalIntervals - (selectedInterval ?? 0)
    return Array.from({ length: newTotalIntervals }, (_, intervalNumber) =>
        appearances.includes(intervalNumber) ? 1 : 0
    )
}

async function hogqlRetentionQuery(
    values: retentionPeopleLogicType['values'],
    selectedInterval: number,
    offset: number = 0
): Promise<RetentionTablePeoplePayload> {
    const retentionQuery = values.querySource as RetentionQuery
    const newAppearanceQuery = wrapRetentionQuery(retentionQuery, selectedInterval, offset)
    const response = await query(newAppearanceQuery)
    const result: RetentionTableAppearanceType[] = response.results.map((row) => ({
        person: row[0],
        appearances: turnAppearancesTo_1s_0s(
            row[1],
            retentionQuery.retentionFilter.total_intervals || 11,
            selectedInterval
        ),
    }))
    return {
        result,
        next: response.hasMore ? response.offset + response.limit : undefined,
        missing_persons: response.missing_actors_count,
    }
}

export const retentionApiService = {
    loadPeople: async (
        values: retentionPeopleLogicType['values'],
        rowIndex: any
    ): Promise<RetentionTablePeoplePayload> => {
        if (hogQLInsightsRetentionFlagEnabled() && values.querySource?.kind === NodeKind.RetentionQuery) {
            return await hogqlRetentionQuery(values, rowIndex)
        }

        const urlParams = toParams({ ...values.apiFilters, selected_interval: rowIndex })
        return api.get<RetentionTablePeoplePayload>(`api/person/retention/?${urlParams}`)
    },
    loadMorePeople: async (
        values: retentionPeopleLogicType['values'],
        rowIndex: any
    ): Promise<RetentionTablePeoplePayload> => {
        if (typeof values.people.next === 'number') {
            return await hogqlRetentionQuery(values, rowIndex, values.people.next)
        }

        return api.get<RetentionTablePeoplePayload>(values.people.next as string)
    },
}

export const retentionPeopleLogic = kea<retentionPeopleLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY)),
    path((key) => ['scenes', 'retention', 'retentionPeopleLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['querySource']],
        actions: [insightVizDataLogic(props), ['loadDataSuccess']],
    })),
    actions(() => ({
        clearPeople: true,
        loadMorePeople: (rowIndex: number) => rowIndex,
        loadMorePeopleSuccess: (payload: RetentionTablePeoplePayload) => ({ payload }),
    })),
    loaders(({ values }) => ({
        people: {
            __default: {} as RetentionTablePeoplePayload,
            loadPeople: async (rowIndex: number) => {
                return await retentionApiService.loadPeople(values, rowIndex)
            },
        },
    })),
    reducers({
        people: {
            clearPeople: () => ({}),
            loadPeople: () => ({}),
            loadMorePeopleSuccess: (_, { payload }) => payload,
        },
        peopleLoadingMore: [
            false,
            {
                loadMorePeople: () => true,
                loadMorePeopleSuccess: () => false,
            },
        ],
    }),
    selectors(() => ({
        apiFilters: [(s) => [s.querySource], (querySource) => (querySource ? queryNodeToFilter(querySource) : {})],
    })),
    listeners(({ actions, values }) => ({
        loadDataSuccess: () => {
            // clear people when changing the insight filters
            actions.clearPeople()
        },
        loadMorePeople: async (rowIndex) => {
            if (values.people.next) {
                const peopleResult: RetentionTablePeoplePayload = await retentionApiService.loadMorePeople(
                    values,
                    rowIndex
                )
                const newPayload: RetentionTablePeoplePayload = {
                    result: [...(values.people.result || []), ...(peopleResult.result || [])],
                    next: peopleResult.next,
                    missing_persons: (peopleResult.missing_persons || 0) + (values.people.missing_persons || 0),
                }
                actions.loadMorePeopleSuccess(newPayload)
            }
        },
    })),
])
