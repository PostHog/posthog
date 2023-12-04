import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { groupsModel, Noun } from '~/models/groupsModel'
import { isLifecycleQuery, isStickinessQuery } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import type { retentionModalLogicType } from './retentionModalLogicType'
import { retentionPeopleLogic } from './retentionPeopleLogic'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionModalLogic = kea<retentionModalLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY)),
    path((key) => ['scenes', 'retention', 'retentionModalLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['querySource'], groupsModel, ['aggregationLabel']],
        actions: [retentionPeopleLogic(props), ['loadPeople']],
    })),
    actions(() => ({
        openModal: (rowIndex: number) => ({ rowIndex }),
        closeModal: true,
    })),
    reducers({
        selectedRow: [
            null as number | null,
            {
                openModal: (_, { rowIndex }) => rowIndex,
                closeModal: () => null,
            },
        ],
    }),
    selectors({
        aggregationTargetLabel: [
            (s) => [s.querySource, s.aggregationLabel],
            (querySource, aggregationLabel): Noun => {
                const aggregation_group_type_index =
                    isLifecycleQuery(querySource) || isStickinessQuery(querySource)
                        ? undefined
                        : querySource?.aggregation_group_type_index
                return aggregationLabel(aggregation_group_type_index)
            },
        ],
    }),
    listeners(({ actions }) => ({
        openModal: ({ rowIndex }) => {
            actions.loadPeople(rowIndex)
        },
    })),
])
