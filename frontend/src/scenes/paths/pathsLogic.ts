import { kea } from 'kea'
import { combineUrl, encodeParams, router } from 'kea-router'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { pathsLogicType } from './pathsLogicType'
import { AnyPropertyFilter, FilterType, PathType, SharedInsightLogicProps, ViewType } from '~/types'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'

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

export function cleanPathParams(filters: Partial<FilterType>): Partial<FilterType> {
    return {
        start_point: filters.start_point || undefined,
        end_point: filters.end_point || undefined,
        step_limit: filters.step_limit || DEFAULT_STEP_LIMIT,
        // TODO: use FF for path_type undefined
        path_type: filters.path_type ? filters.path_type || PathType.PageView : undefined,
        include_event_types: filters.include_event_types || (filters.funnel_filter ? [] : [PathType.PageView]),
        path_groupings: filters.path_groupings || [],
        exclude_events: filters.exclude_events || [],
        ...(filters.include_event_types ? { include_event_types: filters.include_event_types } : {}),
        date_from: filters.date_from,
        date_to: filters.date_to,
        insight: ViewType.PATHS,
        ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
        path_start_key: filters.path_start_key || undefined,
        path_end_key: filters.path_end_key || undefined,
        path_dropoff_key: filters.path_dropoff_key || undefined,
        funnel_filter: filters.funnel_filter || {},
        funnel_paths: filters.funnel_paths,
        properties: filters.properties,
    }
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
    props: {} as SharedInsightLogicProps,
    key: (props) => {
        return props.dashboardItemId || DEFAULT_PATH_LOGIC_KEY
    },
    connect: (props: SharedInsightLogicProps) => ({
        actions: [
            insightHistoryLogic,
            ['createInsight'],
            insightLogic({ id: props.dashboardItemId || 'new' }),
            ['updateInsightFilters', 'startQuery', 'endQuery', 'abortQuery', 'setFilters', 'loadResults'],
        ],
        values: [insightLogic({ id: props.dashboardItemId || 'new' }), ['insight', 'filters', 'results']],
    }),
    actions: {
        setProperties: (properties) => ({ properties }),
        setCachedResults: (filters: Partial<FilterType>, results: any) => ({ filters, results }),
        showPathEvents: (event) => ({ event }),
        updateExclusions: (filters: AnyPropertyFilter[]) => ({ exclusions: filters.map(({ value }) => value) }),
        openPersonsModal: (path_start_key?: string, path_end_key?: string, path_dropoff_key?: string) => ({
            path_start_key,
            path_end_key,
            path_dropoff_key,
        }),
        viewPathToFunnel: (pathItemCard: any) => ({ pathItemCard }),
    },
    listeners: ({ actions, values }) => ({
        showPathEvents: ({ event }) => {
            if (values.filters.include_event_types) {
                const include_event_types = values.filters.include_event_types.includes(event)
                    ? values.filters.include_event_types.filter((e) => e !== event)
                    : [...values.filters.include_event_types, event]
                actions.setFilters({ include_event_types })
            } else {
                actions.setFilters({ include_event_types: [event] })
            }
        },
        setProperties: ({ properties }) => {
            actions.setFilters({ properties })
        },
        updateExclusions: ({ exclusions }) => {
            actions.setFilters({ exclude_events: exclusions as string[] })
        },
        openPersonsModal: ({ path_start_key, path_end_key, path_dropoff_key }) => {
            personsModalLogic.actions.loadPeople({
                action: 'session',
                label: path_dropoff_key || path_start_key || path_end_key || 'Pageview',
                date_from: '',
                date_to: '',
                pathsDropoff: Boolean(path_dropoff_key),
                filters: { ...values.filters, path_start_key, path_end_key, path_dropoff_key },
            })
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
                combineUrl(
                    '/insights',
                    encodeParams({
                        insight: ViewType.FUNNELS,
                        events,
                        date_from: values.filters.date_from,
                    })
                ).url
            )
        },
    }),
    selectors: {
        paths: [
            (s) => [s.results],
            (results: PathResult) => {
                const { paths, error } = results

                const nodes: Record<string, any> = {}
                for (const path of paths) {
                    if (!nodes[path.source]) {
                        nodes[path.source] = { name: path.source }
                    }
                    if (!nodes[path.target]) {
                        nodes[path.target] = { name: path.target }
                    }
                }

                const response = {
                    nodes: Object.values(nodes),
                    links: paths,
                    error,
                }
                return response
            },
        ],
        filter: [(s) => [s.filters], (filters) => filters],
        loadedFilter: [
            (s) => [s.results, s.filters],
            (results: PathResult, filters: Partial<FilterType>) => results?.filter || filters,
        ],
    },
})
