import { kea } from 'kea'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { Noun, groupsModel } from '~/models/groupsModel'
import { InsightLogicProps } from '~/types'
import { retentionPeopleLogic } from './retentionPeopleLogic'
import { retentionLogic } from './retentionLogic'

import type { retentionModalLogicType } from './retentionModalLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionModalLogic = kea<retentionModalLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY),
    path: (key) => ['scenes', 'retention', 'retentionModalLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [
            retentionLogic(props),
            ['filters', 'results', 'retentionReference'],
            groupsModel,
            ['aggregationLabel'],
        ],
        actions: [retentionPeopleLogic(props), ['loadPeople']],
    }),
    actions: () => ({
        openModal: (rowIndex?: number) => ({ rowIndex }),
        closeModal: true,
    }),
    reducers: {
        isVisible: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        selectedRow: [
            null as number | null,
            {
                openModal: (_, { rowIndex }) => rowIndex || null,
            },
        ],
    },
    selectors: {
        aggregationTargetLabel: [
            (s) => [s.filters, s.aggregationLabel],
            (filters, aggregationLabel): Noun => {
                return aggregationLabel(filters.aggregation_group_type_index)
            },
        ],
    },
    listeners: ({ actions }) => ({
        openModal: ({ rowIndex }) => {
            if (rowIndex) {
                actions.loadPeople(rowIndex)
            }
        },
    }),
})
