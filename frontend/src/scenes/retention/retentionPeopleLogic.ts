import { loaders } from 'kea-loaders'
import { kea, props, key, path, connect, actions, reducers, selectors, listeners } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { RetentionTablePeoplePayload } from 'scenes/retention/types'
import { InsightLogicProps } from '~/types'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import type { retentionPeopleLogicType } from './retentionPeopleLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

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
                const urlParams = toParams({ ...values.apiFilters, selected_interval: rowIndex })
                return await api.get<RetentionTablePeoplePayload>(`api/person/retention/?${urlParams}`)
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
                const peopleResult: RetentionTablePeoplePayload = await api.get(values.people.next)
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
