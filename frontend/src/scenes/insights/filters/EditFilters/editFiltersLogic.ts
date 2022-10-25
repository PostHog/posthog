import { actions, connect, kea, key, path, props, reducers } from 'kea'
import type { editFiltersLogicType } from './editFiltersLogicType'
import { InsightLogicProps } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { forms } from 'kea-forms'

export const editFiltersLogic = kea<editFiltersLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'EditFilters', 'editFiltersLogic', key]),
    connect((props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters']],
        values: [insightLogic(props), ['filters']],
    })),
    actions({
        openEditFilters: (filters: Record<string, any>) => ({ filters }),
        closeEditFilters: true,
        setEditText: (value: string) => ({ value }),
    }),
    forms({
        editForm: {
            defaults: {
                editText: '',
            },
        },
    }),
    reducers({
        editOpen: [false, { openEditFilters: () => true, closeEditFilters: () => false }],
        editText: [
            '',
            {
                openEditFilters: (_, { filters }) => JSON.stringify(filters, null, 4),
                setEditText: (_, { value }) => value,
            },
        ],
    }),
])
