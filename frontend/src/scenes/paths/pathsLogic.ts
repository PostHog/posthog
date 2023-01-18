import { kea } from 'kea'
import { router } from 'kea-router'

import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'

import type { pathsLogicType } from './pathsLogicType'
import { InsightLogicProps, FilterType, PathType, PropertyFilter, InsightType, PathsFilterType } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { isPathsFilter } from 'scenes/insights/sharedUtils'
import { urls } from 'scenes/urls'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { buildPeopleUrl, pathsTitle } from 'scenes/trends/persons-modal/persons-modal-utils'

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

export const pathsLogic = kea<pathsLogicType>({
    path: (key) => ['scenes', 'paths', 'pathsLogic', key],
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_PATH_LOGIC_KEY),

    connect: (props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['filters as inflightFilters', 'insight', 'insightLoading'],
            trendsLogic(props),
            ['aggregationTargetLabel'],
        ],
        actions: [insightLogic(props), ['loadResultsSuccess']],
    }),

    actions: {
        setProperties: (properties: PropertyFilter[]) => ({ properties }),
        setFilter: (filter: Partial<PathsFilterType>) => ({ filter }),
        openPersonsModal: (props: { path_start_key?: string; path_end_key?: string; path_dropoff_key?: string }) =>
            props,
        viewPathToFunnel: (pathItemCard: any) => ({ pathItemCard }),
    },
    listeners: ({ values, props }) => ({
        setProperties: ({ properties }) => {
            insightLogic(props).actions.setFilters(cleanFilters({ ...values.filter, properties }))
        },
        setFilter: ({ filter }) => {
            insightLogic(props).actions.setFilters(cleanFilters({ ...values.filter, ...filter }))
        },
        openPersonsModal: ({ path_start_key, path_end_key, path_dropoff_key }) => {
            const filters: Partial<PathsFilterType> = {
                ...values.filter,
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
                    date_from: values.filter.date_from,
                })
            )
        },
    }),
    selectors: {
        filter: [
            (s) => [s.inflightFilters],
            (inflightFilters): Partial<PathsFilterType> =>
                inflightFilters && isPathsFilter(inflightFilters) ? inflightFilters : {},
        ],
        loadedFilters: [
            (s) => [s.insight],
            ({ filters }): Partial<PathsFilterType> => (filters && isPathsFilter(filters) ? filters : {}),
        ],
        results: [
            (s) => [s.insight],
            ({ filters, result }): PathNode[] => (filters && isPathsFilter(filters) ? result || [] : []),
        ],
        resultsLoading: [(s) => [s.insightLoading], (insightLoading) => insightLoading],
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
        pathsError: [(s) => [s.insight], (insight): PathNode => insight.result?.error],
        loadedFilter: [
            (s) => [s.results, s.filter],
            (results: PathResult, filter: Partial<FilterType>) => results?.filter || filter,
        ],
        propertiesForUrl: [
            (s) => [s.filter],
            (filter: Partial<FilterType>) => {
                let result: Partial<FilterType> = {
                    insight: InsightType.PATHS,
                }
                if (filter && Object.keys(filter).length > 0) {
                    result = {
                        ...result,
                        ...filter,
                    }
                }
                return Object.keys(result).length === 0 ? '' : result
            },
        ],
        taxonomicGroupTypes: [
            (s) => [s.filter],
            (filter: Partial<PathsFilterType>) => {
                const taxonomicGroupTypes: TaxonomicFilterGroupType[] = []
                if (filter.include_event_types) {
                    if (filter.include_event_types.includes(PathType.PageView)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.PageviewUrls)
                    }
                    if (filter.include_event_types.includes(PathType.Screen)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.Screens)
                    }
                    if (filter.include_event_types.includes(PathType.CustomEvent)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.CustomEvents)
                    }
                }

                taxonomicGroupTypes.push(TaxonomicFilterGroupType.Wildcards)
                return taxonomicGroupTypes
            },
        ],
    },
})
