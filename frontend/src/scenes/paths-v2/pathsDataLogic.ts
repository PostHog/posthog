import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { router } from 'kea-router'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { OpenPersonsModalProps, openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { pathsTitle } from 'scenes/trends/persons-modal/persons-modal-utils'
import { urls } from 'scenes/urls'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { InsightActorsQuery, InsightVizNode, NodeKind, PathsLink, PathsQuery } from '~/queries/schema/schema-general'
import { isPathsQuery } from '~/queries/utils'
import { ActionFilter, InsightLogicProps, PathType, PropertyFilterType, PropertyOperator } from '~/types'

import { PathNodeData } from './pathUtils'
import type { pathsDataLogicType } from './pathsDataLogicType'
import { Paths, PathsNode } from './types'

export const DEFAULT_STEP_LIMIT = 5

const DEFAULT_PATH_LOGIC_KEY = 'default_path_key'

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
                'funnelPathsFilter',
                'dateRange',
                'theme',
            ],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [insightVizDataLogic(props), ['updateInsightFilter', 'updateQuerySource']],
    })),

    actions({
        openPersonsModal: (props: { path_start_key?: string; path_end_key?: string; path_dropoff_key?: string }) =>
            props,
        viewPathToFunnel: (pathItemCard: PathNodeData) => ({ pathItemCard }),
    }),

    selectors({
        results: [
            (s) => [s.insightQuery, s.insightData],
            (insightQuery, insightData): PathsLink[] => {
                return isPathsQuery(insightQuery) ? (insightData?.result ?? []) : []
            },
        ],
        paths: [
            (s) => [s.results],
            (results): Paths => {
                const nodes: Record<string, PathsNode> = {}
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
                    if (pathsFilter.includeEventTypes.includes(PathType.PageView)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.PageviewUrls)
                    }
                    if (pathsFilter.includeEventTypes.includes(PathType.Screen)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.Screens)
                    }
                    if (pathsFilter.includeEventTypes.includes(PathType.CustomEvent)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.CustomEvents)
                    }
                }
                taxonomicGroupTypes.push(TaxonomicFilterGroupType.Wildcards)
                return taxonomicGroupTypes
            },
        ],
    }),

    listeners(({ values }) => ({
        openPersonsModal: ({ path_start_key, path_end_key, path_dropoff_key }) => {
            const query: InsightActorsQuery = {
                kind: NodeKind.InsightActorsQuery,
                source: {
                    ...values.vizQuerySource,
                    pathsFilter: {
                        ...(values.vizQuerySource as PathsQuery)?.pathsFilter,
                        pathStartKey: path_start_key,
                        pathEndKey: path_end_key,
                        pathDropoffKey: path_dropoff_key,
                    },
                } as PathsQuery,
            }
            const modalProps: OpenPersonsModalProps = {
                title: pathsTitle({
                    label: path_dropoff_key || path_start_key || path_end_key || 'Pageview',
                    mode: path_dropoff_key ? 'dropOff' : path_start_key ? 'continue' : 'completion',
                }),
                query,
                additionalSelect: {
                    value_at_data_point: 'event_count',
                    matched_recordings: 'matched_recordings',
                },
                orderBy: ['event_count DESC, actor_id DESC'],
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
                const url = new URL(currentItemCard.name.replace(/(^[0-9]+_)/, ''))
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
                                value: url.href,
                            },
                        ],
                    }),
                })
                currentItemCard = currentItemCard.targetLinks[0]?.source
            }
            events.sort((a, b) => (a.order ?? 0) - (b.order ?? 0))

            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.FunnelsQuery,
                    series: actionsAndEventsToSeries({ events: events.reverse() }, true, MathAvailability.None),
                    dateRange: {
                        date_from: values.dateRange?.date_from,
                    },
                },
            }

            if (events.length > 0) {
                router.actions.push(urls.insightNew({ query }))
            }
        },
    })),
])
