import { kea } from 'kea'
import { router } from 'kea-router'
import { insightLogic } from 'scenes/insights/insightLogic'
import { pathsLogicType } from './pathsLogicType'
import { InsightLogicProps, FilterType, PathType, PropertyFilter, InsightType } from '~/types'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { urls } from 'scenes/urls'

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
interface PathResult {
    paths: PathNode[]
    filter: Partial<FilterType>
    error?: boolean
}

interface PathNode {
    target: string
    source: string
    value: number
}

export const pathsLogic = kea<pathsLogicType<PathNode>>({
    path: (key) => ['scenes', 'paths', 'pathsLogic', key],
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_PATH_LOGIC_KEY),

    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters as filter', 'insight', 'insightLoading']],
        actions: [insightLogic(props), ['loadResultsSuccess']],
    }),

    actions: {
        setProperties: (properties: PropertyFilter[]) => ({ properties }),
        setFilter: (filter: Partial<FilterType>) => ({ filter }),
        showPathEvents: (event) => ({ event }),
        updateExclusions: (exclusions: string[]) => ({ exclusions }),
        openPersonsModal: (path_start_key?: string, path_end_key?: string, path_dropoff_key?: string) => ({
            path_start_key,
            path_end_key,
            path_dropoff_key,
        }),
        viewPathToFunnel: (pathItemCard: any) => ({ pathItemCard }),
    },
    listeners: ({ actions, values, props }) => ({
        setProperties: ({ properties }) => {
            insightLogic(props).actions.setFilters(cleanFilters({ ...values.filter, properties }))
        },
        setFilter: ({ filter }) => {
            insightLogic(props).actions.setFilters(cleanFilters({ ...values.filter, ...filter }))
        },
        updateExclusions: ({ exclusions }) => {
            actions.setFilter({ exclude_events: exclusions })
        },
        openPersonsModal: ({ path_start_key, path_end_key, path_dropoff_key }) => {
            personsModalLogic.actions.loadPeople({
                action: 'session',
                label: path_dropoff_key || path_start_key || path_end_key || 'Pageview',
                date_from: '',
                date_to: '',
                pathsDropoff: Boolean(path_dropoff_key),
                filters: { ...values.filter, path_start_key, path_end_key, path_dropoff_key },
            })
        },
        showPathEvents: ({ event }) => {
            const { filter } = values
            if (filter.include_event_types) {
                const include_event_types = filter.include_event_types.includes(event)
                    ? filter.include_event_types.filter((e) => e !== event)
                    : [...filter.include_event_types, event]
                actions.setFilter({ ...filter, include_event_types })
            } else {
                actions.setFilter({ ...filter, include_event_types: [event] })
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
        loadedFilters: [
            (s) => [s.insight],
            ({ filters }): Partial<FilterType> => (filters?.insight === InsightType.PATHS ? filters ?? {} : {}),
        ],
        results: [
            (s) => [s.insight],
            ({ filters, result }): PathNode[] => (filters?.insight === InsightType.PATHS ? result || [] : []),
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
        wildcards: [
            (s) => [s.filter],
            (filter: Partial<FilterType>) => {
                return filter.path_groupings?.map((name) => ({ name }))
            },
        ],
    },
})
