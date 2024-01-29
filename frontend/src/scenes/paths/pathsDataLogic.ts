import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { router } from 'kea-router'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { buildPeopleUrl, pathsTitle } from 'scenes/trends/persons-modal/persons-modal-utils'
import { openPersonsModal, OpenPersonsModalProps } from 'scenes/trends/persons-modal/PersonsModal'
import { urls } from 'scenes/urls'

import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { NodeKind, PathsQuery } from '~/queries/schema'
import { isPathsQuery } from '~/queries/utils'
import {
    ActionFilter,
    InsightLogicProps,
    InsightType,
    PathsFilterType,
    PathType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import type { pathsDataLogicType } from './pathsDataLogicType'
import { PathNodeData } from './pathUtils'

export const DEFAULT_STEP_LIMIT = 5

const DEFAULT_PATH_LOGIC_KEY = 'default_path_key'

export interface PathNode {
    target: string
    source: string
    value: number
}

export const pathsDataLogic = kea<pathsDataLogicType>([
    path((key) => ['scenes', 'paths', 'pathsDataLogic', key]),
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_PATH_LOGIC_KEY)),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            [
                'querySource as vizQuerySource',
                'insightQuery',
                'insightData',
                'insightDataLoading',
                'insightDataError',
                'pathsFilter',
                'dateRange',
            ],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [insightVizDataLogic(props), ['updateInsightFilter']],
    })),

    actions({
        openPersonsModal: (props: { path_start_key?: string; path_end_key?: string; path_dropoff_key?: string }) =>
            props,
        viewPathToFunnel: (pathItemCard: PathNodeData) => ({ pathItemCard }),
    }),

    selectors({
        results: [
            (s) => [s.insightQuery, s.insightData],
            (insightQuery, insightData): PathNode[] => {
                return isPathsQuery(insightQuery) ? insightData?.result ?? [] : []
            },
        ],
        paths: [
            (s) => [s.results],
            (results) => {
                const nodes: Record<string, any> = {}
                for (const path of results) {
                    if (!nodes[path.source]) {
                        nodes[path.source] = { name: path.source }
                    }
                    if (!nodes[path.target]) {
                        nodes[path.target] = { name: path.target }
                    }
                }

                return {
                    nodes: Object.values(nodes),
                    links: results,
                }
            },
        ],
        taxonomicGroupTypes: [
            (s) => [s.pathsFilter],
            (pathsFilter) => {
                const taxonomicGroupTypes: TaxonomicFilterGroupType[] = []
                if (pathsFilter?.includeEventTypes) {
                    if (pathsFilter?.includeEventTypes.includes(PathType.PageView)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.PageviewUrls)
                    }
                    if (pathsFilter?.includeEventTypes.includes(PathType.Screen)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.Screens)
                    }
                    if (pathsFilter?.includeEventTypes.includes(PathType.CustomEvent)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.CustomEvents)
                    }
                }
                taxonomicGroupTypes.push(TaxonomicFilterGroupType.Wildcards)
                return taxonomicGroupTypes
            },
        ],
        hogQLInsightsPathsFlagEnabled: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.HOGQL_INSIGHTS_PATHS],
        ],
    }),

    listeners(({ values }) => ({
        openPersonsModal: ({ path_start_key, path_end_key, path_dropoff_key }) => {
            const filters: Partial<PathsFilterType> = {
                ...queryNodeToFilter(values.vizQuerySource as PathsQuery),
                path_start_key,
                path_end_key,
                path_dropoff_key,
            }
            const modalProps: OpenPersonsModalProps = {
                url: buildPeopleUrl({
                    date_from: '',
                    filters,
                    response: values.insightData,
                }),
                title: pathsTitle({
                    label: path_dropoff_key || path_start_key || path_end_key || 'Pageview',
                    mode: path_dropoff_key ? 'dropOff' : path_start_key ? 'continue' : 'completion',
                }),
                orderBy: ['id'],
            }
            if (values.hogQLInsightsPathsFlagEnabled && values.vizQuerySource?.kind === NodeKind.PathsQuery) {
                modalProps['query'] = {
                    kind: NodeKind.InsightActorsQuery,
                    source: {
                        ...values.vizQuerySource,
                        pathsFilter: {
                            ...values.vizQuerySource.pathsFilter,
                            pathStartKey: path_start_key,
                            pathEndKey: path_end_key,
                            pathDropoffKey: path_dropoff_key,
                        },
                    },
                }
                modalProps['additionalSelect'] = {
                    value_at_data_point: 'event_count',
                    matched_recordings: 'matched_recordings',
                }
            }
            openPersonsModal(modalProps)
        },
        viewPathToFunnel: ({ pathItemCard }) => {
            const events: ActionFilter[] = []
            let currentItemCard = pathItemCard
            while (currentItemCard) {
                const name = currentItemCard.name.includes('http')
                    ? '$pageview'
                    : currentItemCard.name.replace(/(^[0-9]+_)/, '')
                events.push({
                    id: name,
                    name: name,
                    type: 'events',
                    order: currentItemCard.depth,
                    ...(currentItemCard.name.includes('http') && {
                        properties: [
                            {
                                key: '$current_url',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                                value: currentItemCard.name.replace(/(^[0-9]+_)/, ''),
                            },
                        ],
                    }),
                })
                currentItemCard = currentItemCard.targetLinks[0]?.source
            }
            events.sort((a, b) => (a.order ?? 0) - (b.order ?? 0))

            if (events.length > 0) {
                router.actions.push(
                    urls.insightNew({
                        insight: InsightType.FUNNELS,
                        events: events.reverse(),
                        date_from: values.dateRange?.date_from,
                    })
                )
            }
        },
    })),
])
