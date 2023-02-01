import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { RetentionTablePeoplePayload } from 'scenes/retention/types'
import { InsightLogicProps } from '~/types'
import { retentionLogic } from './retentionLogic'

import type { retentionPeopleLogicType } from './retentionPeopleLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionPeopleLogic = kea<retentionPeopleLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY),
    path: (key) => ['scenes', 'retention', 'retentionPeopleLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [retentionLogic(props), ['filters']],
        actions: [insightLogic(props), ['loadResultsSuccess']],
    }),
    actions: () => ({
        loadMorePeople: true,
        updatePeople: (people: RetentionTablePeoplePayload) => ({ people }),
        clearPeople: true,
    }),
    loaders: ({ values }) => ({
        people: {
            __default: {} as RetentionTablePeoplePayload,
            loadPeople: async (rowIndex: number) => {
                const urlParams = toParams({ ...values.filters, selected_interval: rowIndex })
                return (await api.get(`api/person/retention/?${urlParams}`)) as RetentionTablePeoplePayload
            },
        },
    }),
    reducers: {
        people: {
            clearPeople: () => ({}),
            updatePeople: (_, { people }) => people,
        },
        loadingMore: [
            false,
            {
                loadMorePeople: () => true,
                updatePeople: () => false,
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        loadResultsSuccess: async () => {
            actions.clearPeople()
        },
        loadMorePeople: async () => {
            if (values.people.next) {
                const peopleResult: RetentionTablePeoplePayload = await api.get(values.people.next)
                const newPeople: RetentionTablePeoplePayload = {
                    result: [...(values.people.result || []), ...(peopleResult.result || [])],
                    next: peopleResult.next,
                    missing_persons: (peopleResult.missing_persons || 0) + (values.people.missing_persons || 0),
                }
                actions.updatePeople(newPeople)
            }
        },
    }),
})
