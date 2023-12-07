import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { toParams } from 'lib/utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { RetentionTablePeoplePayload } from 'scenes/retention/types'

import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { query } from '~/queries/query'
import { NodeKind, RetentionAppearanceQuery, RetentionQuery } from '~/queries/schema'
import { InsightLogicProps } from '~/types'

import type { retentionPeopleLogicType } from './retentionPeopleLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export function wrapRetentionQuery(
    query: RetentionQuery,
    selectedInterval: number,
    offset = 0
): RetentionAppearanceQuery {
    return {
        kind: NodeKind.RetentionAppearanceQuery,
        source: query,
        offset,
        selectedInterval,
    }
}

const hogQLInsightsRetentionFlagEnabled = (): boolean =>
    Boolean(featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.HOGQL_INSIGHTS_RETENTION])

export const retentionApiService = {
    loadPeople: async (
        values: retentionPeopleLogicType['values'],
        rowIndex: any
    ): Promise<RetentionTablePeoplePayload> => {
        if (hogQLInsightsRetentionFlagEnabled() && values.querySource?.kind === NodeKind.RetentionQuery) {
            const newAppearanceQuery = wrapRetentionQuery(values.querySource, rowIndex)
            return query(newAppearanceQuery)
        }

        const urlParams = toParams({ ...values.apiFilters, selected_interval: rowIndex })
        return api.get<RetentionTablePeoplePayload>(`api/person/retention/?${urlParams}`)
    },
    loadMorePeople: async (nextUrl: string): Promise<RetentionTablePeoplePayload> => {
        return api.get<RetentionTablePeoplePayload>(nextUrl)
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
        loadMorePeople: true,
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
        loadMorePeople: async () => {
            if (values.people.next) {
                const peopleResult: RetentionTablePeoplePayload = await retentionApiService.loadMorePeople(
                    values.people.next
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
