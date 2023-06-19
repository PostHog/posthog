import { kea, path, props, key, connect, selectors, actions, listeners } from 'kea'
import { InsightLogicProps, FilterType, PathType, PathsFilterType, InsightType } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import type { pathsDataLogicType } from './pathsDataLogicType'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { isPathsQuery } from '~/queries/utils'
import { PathNodeData } from './pathUtils'
import { buildPeopleUrl, pathsTitle } from 'scenes/trends/persons-modal/persons-modal-utils'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { InsightQueryNode } from '~/queries/schema'

export const DEFAULT_STEP_LIMIT = 5

export const pathOptionsToLabels = {
    [PathType.PageView]: 'Page views (Web)',
    [PathType.Screen]: 'Screen views (Mobile)',
    [PathType.CustomEvent]: 'Custom events',
}

export const pathOptionsToProperty = {
    [PathType.PageView]: '$current_url',
    [PathType.Screen]: '$screen_name',
    [PathType.CustomEvent]: 'custom_event',
}

const DEFAULT_PATH_LOGIC_KEY = 'default_path_key'
export interface PathResult {
    paths: PathNode[]
    filter: Partial<FilterType>
    error?: boolean
}

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
                if (pathsFilter?.include_event_types) {
                    if (pathsFilter?.include_event_types.includes(PathType.PageView)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.PageviewUrls)
                    }
                    if (pathsFilter?.include_event_types.includes(PathType.Screen)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.Screens)
                    }
                    if (pathsFilter?.include_event_types.includes(PathType.CustomEvent)) {
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
            const filters: Partial<PathsFilterType> = {
                ...queryNodeToFilter(values.vizQuerySource as InsightQueryNode),
                path_start_key,
                path_end_key,
                path_dropoff_key,
            }
            const personsUrl = buildPeopleUrl({
                date_from: '',
                date_to: '',
                filters,
            })
            if (personsUrl) {
                openPersonsModal({
                    url: personsUrl,
                    title: pathsTitle({
                        label: path_dropoff_key || path_start_key || path_end_key || 'Pageview',
                        isDropOff: Boolean(path_dropoff_key),
                    }),
                })
            }
        },
        viewPathToFunnel: ({ pathItemCard }) => {
            const events = []
            let currentItemCard = pathItemCard
            while (currentItemCard.targetLinks.length > 0) {
                const name = currentItemCard.name.includes('http')
                    ? '$pageview'
                    : currentItemCard.name.replace(/(^[0-9]+_)/, '')
                events.push({
                    id: name,
                    name: name,
                    type: 'events',
                    order: currentItemCard.depth - 1,
                    ...(currentItemCard.name.includes('http') && {
                        properties: [
                            {
                                key: '$current_url',
                                operator: 'exact',
                                type: 'event',
                                value: currentItemCard.name.replace(/(^[0-9]+_)/, ''),
                            },
                        ],
                    }),
                })
                currentItemCard = currentItemCard.targetLinks[0].source
            }
            router.actions.push(
                urls.insightNew({
                    insight: InsightType.FUNNELS,
                    events,
                    date_from: values.dateRange?.date_from,
                })
            )
        },
    })),
])
