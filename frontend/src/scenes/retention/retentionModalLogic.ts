import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { retentionToActorsQuery } from 'scenes/retention/queries'
import { urls } from 'scenes/urls'

import { groupsModel, Noun } from '~/models/groupsModel'
import { ActorsQuery, DataTableNode, NodeKind, RetentionQuery } from '~/queries/schema'
import { isInsightActorsQuery, isLifecycleQuery, isRetentionQuery, isStickinessQuery } from '~/queries/utils'
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
        selectedInterval: [
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
        ActorsQuery: [
            (s) => [s.querySource, s.selectedInterval],
            (querySource: RetentionQuery, selectedInterval): ActorsQuery | null => {
                if (!querySource) {
                    return null
                }
                return retentionToActorsQuery(querySource, selectedInterval ?? 0)
            },
        ],
        exploreUrl: [
            (s) => [s.ActorsQuery],
            (ActorsQuery): string | null => {
                if (!ActorsQuery) {
                    return null
                }
                const query: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    source: ActorsQuery,
                    full: true,
                }
                if (
                    isInsightActorsQuery(ActorsQuery.source) &&
                    isRetentionQuery(ActorsQuery.source.source) &&
                    ActorsQuery.source.source.aggregation_group_type_index !== undefined
                ) {
                    query.showPropertyFilter = false
                }
                return urls.insightNew(undefined, undefined, JSON.stringify(query))
            },
        ],
    }),
    listeners(({ actions }) => ({
        openModal: ({ rowIndex }) => {
            actions.loadPeople(rowIndex)
        },
    })),
])
