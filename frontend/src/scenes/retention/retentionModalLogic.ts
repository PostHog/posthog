import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { retentionToActorsQuery } from 'scenes/retention/queries'
import { urls } from 'scenes/urls'

import { groupsModel, Noun } from '~/models/groupsModel'
import {
    ActorsQuery,
    DataTableNode,
    InsightActorsQuery,
    NodeKind,
    RetentionQuery,
} from '~/queries/schema/schema-general'
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
        values: [
            insightVizDataLogic(props),
            ['querySource', 'retentionFilter', 'theme'],
            groupsModel,
            ['aggregationLabel'],
            featureFlagLogic,
            ['featureFlags'],
        ],
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
        actorsQuery: [
            (s) => [s.querySource, s.selectedInterval],
            (querySource: RetentionQuery, selectedInterval): ActorsQuery | null => {
                if (!querySource) {
                    return null
                }
                return retentionToActorsQuery(querySource, selectedInterval ?? 0)
            },
        ],
        insightEventsQueryUrl: [
            (s) => [s.actorsQuery],
            (actorsQuery: ActorsQuery): string | null => {
                if (!actorsQuery) {
                    return null
                }

                // Generate insight events query from actors query
                const { select: _select, ...source } = actorsQuery

                const { includeRecordings, ...insightActorsQuery } = source.source as InsightActorsQuery

                const query: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        source: insightActorsQuery,
                        select: ['*', 'event', 'person', 'timestamp'],
                        after: 'all', // Show all events by default because date range is filtered by the source
                    },
                    full: true,
                }

                return urls.insightNew({ query })
            },
        ],
        exploreUrl: [
            (s) => [s.actorsQuery],
            (actorsQuery: ActorsQuery): string | null => {
                if (!actorsQuery) {
                    return null
                }
                const query: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    source: actorsQuery,
                    full: true,
                }
                if (
                    isInsightActorsQuery(actorsQuery.source) &&
                    isRetentionQuery(actorsQuery.source.source) &&
                    actorsQuery.source.source.aggregation_group_type_index !== undefined
                ) {
                    query.showPropertyFilter = false
                }

                return urls.insightNew({ query })
            },
        ],
    }),
    listeners(({ actions }) => ({
        openModal: ({ rowIndex }) => {
            actions.loadPeople(rowIndex)
        },
    })),
])
