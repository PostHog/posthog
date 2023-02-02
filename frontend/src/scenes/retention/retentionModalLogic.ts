import { kea } from 'kea'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { Noun, groupsModel } from '~/models/groupsModel'
import { InsightLogicProps } from '~/types'
import { retentionPeopleLogic } from './retentionPeopleLogic'
import { abstractRetentionLogic } from './abstractRetentionLogic'

import type { retentionModalLogicType } from './retentionModalLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionModalLogic = kea<retentionModalLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY),
    path: (key) => ['scenes', 'retention', 'retentionModalLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [abstractRetentionLogic(props), ['retentionFilter'], groupsModel, ['aggregationLabel']],
        actions: [retentionPeopleLogic(props), ['loadPeople']],
    }),
    actions: () => ({
        openModal: (rowIndex: number) => ({ rowIndex }),
        closeModal: true,
    }),
    reducers: {
        selectedRow: [
            null as number | null,
            {
                openModal: (_, { rowIndex }) => rowIndex,
                closeModal: () => null,
            },
        ],
    },
    selectors: {
        aggregationTargetLabel: [
            (s) => [s.retentionFilter, s.aggregationLabel],
            (filters, aggregationLabel): Noun => {
                return aggregationLabel(filters.aggregation_group_type_index)
            },
        ],
    },
    listeners: ({ actions }) => ({
        openModal: ({ rowIndex }) => {
            actions.loadPeople(rowIndex)
        },
    }),
})
