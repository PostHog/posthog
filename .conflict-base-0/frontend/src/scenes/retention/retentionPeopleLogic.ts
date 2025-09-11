import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { queryForActors } from 'scenes/retention/queries'
import { RetentionTablePeoplePayload } from 'scenes/retention/types'

import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { NodeKind, RetentionQuery } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

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
        loadPeople: (selectedInterval: number, breakdownValue?: string | number | null) => ({
            selectedInterval,
            breakdownValue,
        }),
        loadMorePeople: (selectedInterval: number, breakdownValue?: string | number | null) => ({
            selectedInterval,
            breakdownValue,
        }),
        loadMorePeopleSuccess: (payload: RetentionTablePeoplePayload) => ({ payload }),
    })),
    loaders(({ values }) => ({
        people: {
            __default: {} as RetentionTablePeoplePayload,
            loadPeople: async ({
                selectedInterval,
                breakdownValue,
            }: {
                selectedInterval: number
                breakdownValue?: string | number | null
            }) => {
                return await queryForActors(values.querySource as RetentionQuery, selectedInterval, 0, breakdownValue)
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
        loadMorePeople: async ({
            selectedInterval,
            breakdownValue,
        }: {
            selectedInterval: number
            breakdownValue?: string | number | null
        }) => {
            if (values.people.next || values.people.offset) {
                let peopleResult: RetentionTablePeoplePayload
                if (values.people.offset && values.querySource?.kind === NodeKind.RetentionQuery) {
                    peopleResult = await queryForActors(
                        values.querySource,
                        selectedInterval,
                        values.people.offset,
                        breakdownValue
                    )
                } else {
                    peopleResult = await api.get<RetentionTablePeoplePayload>(values.people.next as string)
                }
                const newPayload: RetentionTablePeoplePayload = {
                    result: [...(values.people.result || []), ...(peopleResult.result || [])],
                    next: peopleResult.next,
                    offset: peopleResult.offset,
                    missing_persons: (peopleResult.missing_persons || 0) + (values.people.missing_persons || 0),
                }
                actions.loadMorePeopleSuccess(newPayload)
            }
        },
    })),
])
