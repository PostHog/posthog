import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { retentionToActorsQuery } from 'scenes/retention/queries'
import { urls } from 'scenes/urls'

import { groupsModel, Noun } from '~/models/groupsModel'
import { DataTableNode, NodeKind, PersonsQuery, RetentionQuery } from '~/queries/schema'
import { isInsightPersonsQuery, isLifecycleQuery, isRetentionQuery, isStickinessQuery } from '~/queries/utils'
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
        personsQuery: [
            (s) => [s.querySource, s.selectedInterval],
            (querySource: RetentionQuery, selectedInterval): PersonsQuery | null => {
                if (!querySource) {
                    return null
                }
                return retentionToActorsQuery(querySource, selectedInterval ?? 0)
            },
        ],
        exploreUrl: [
            (s) => [s.personsQuery],
            (personsQuery): string | null => {
                if (!personsQuery) {
                    return null
                }
                const query: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    source: personsQuery,
                    full: true,
                }
                if (
                    isInsightPersonsQuery(personsQuery.source) &&
                    isRetentionQuery(personsQuery.source.source) &&
                    personsQuery.source.source.aggregation_group_type_index !== undefined
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
