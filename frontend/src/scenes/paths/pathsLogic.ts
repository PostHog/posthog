import { kea } from 'kea'
import { objectsEqual, uuid } from 'lib/utils'
import api from 'lib/api'
import { combineUrl, encodeParams, router } from 'kea-router'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { pathsLogicType } from './pathsLogicType'
import { InsightLogicProps, FilterType, PathType, PropertyFilter, ViewType, AnyPropertyFilter } from '~/types'
import { dashboardsModel } from '~/models/dashboardsModel'
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

export const pathsLogic = kea<pathsLogicType<PathNode, PathResult>>({
    props: {} as InsightLogicProps,
    key: (props) => {
        return props.dashboardItemId || DEFAULT_PATH_LOGIC_KEY
    },
    connect: {
        actions: [insightHistoryLogic, ['createInsight']],
    },
    actions: {
        setProperties: (properties) => ({ properties }),
        setFilter: (filter) => filter,
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
    loaders: ({ values, props }) => ({
        results: {
            __default: { paths: [], filter: {} } as PathResult,
            setCachedResults: ({ results, filters }) => {
                return {
                    paths: results,
                    filters: filters,
                }
            },
            loadResults: async (refresh = false, breakpoint) => {
                const filter = { ...values.filter, properties: values.properties }
                if (!refresh && (props.cachedResults || props.preventLoading) && values.filter === props.filters) {
                    return { paths: props.cachedResults, filter }
                }
                const params = { ...filter, ...(refresh ? { refresh: true } : {}) }

                const queryId = uuid()
                const dashboardItemId = props.dashboardItemId || props.fromDashboardItemId
                insightLogic.actions.startQuery(queryId)
                if (dashboardItemId) {
                    dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, true, null)
                }

                let paths
                try {
                    paths = await api.create(`api/insight/path`, params)
                } catch (e) {
                    breakpoint()
                    insightLogic.actions.endQuery(queryId, ViewType.PATHS, null, e)
                    if (dashboardItemId) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, null)
                    }

                    return { paths: [], filter, error: true }
                }
                breakpoint()
                insightLogic.actions.endQuery(queryId, ViewType.PATHS, paths.last_refresh)
                if (dashboardItemId) {
                    dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, paths.last_refresh)
                }

                return { paths: paths.result, filter }
            },
        },
    }),
    reducers: ({ props }) => ({
        filter: [
            (props.filters
                ? cleanPathParams(props.filters)
                : (state: Record<string, any>) =>
                      cleanPathParams(router.selectors.searchParams(state))) as Partial<FilterType>,
            {
                setFilter: (state, filter) => ({ ...state, ...filter }),
                showPathEvents: (state, { event }) => {
                    if (state.include_event_types) {
                        const include_event_types = state.include_event_types.includes(event)
                            ? state.include_event_types.filter((e) => e !== event)
                            : [...state.include_event_types, event]
                        return { ...state, include_event_types }
                    }
                    return { ...state, include_event_types: [event] }
                },
            },
        ],
        properties: [
            (props.filters
                ? props.filters.properties || []
                : (state: Record<string, any>) =>
                      router.selectors.searchParams(state).properties || []) as PropertyFilter[],
            {
                setProperties: (_, { properties }) => properties,
            },
        ],
    }),
    listeners: ({ actions, values, props }) => ({
        setProperties: () => {
            actions.loadResults(true)
        },
        updateExclusions: ({ exclusions }) => {
            actions.setFilter({ exclude_events: exclusions })
        },
        setFilter: () => {
            actions.loadResults(true)
        },
        loadResults: () => {
            insightLogic.actions.setAllFilters({ ...cleanPathParams(values.filter), properties: values.properties })
            if (!props.dashboardItemId) {
                if (!insightLogic.values.insight.id) {
                    actions.createInsight({ ...cleanPathParams(values.filter), properties: values.properties })
                } else {
                    insightLogic.actions.updateInsightFilters(values.filter)
                }
            }
        },
        openPersonsModal: ({ path_start_key, path_end_key, path_dropoff_key }) => {
            personsModalLogic.actions.loadPeople({
                action: 'session', // relic from reusing Trend PersonModal
                label: path_dropoff_key || path_start_key || path_end_key || 'Pageview',
                date_from: '',
                date_to: '',
                pathsDropoff: Boolean(path_dropoff_key),
                filters: { ...values.filter, path_start_key, path_end_key, path_dropoff_key },
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
                        date_from: values.filter.date_from,
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
        loadedFilter: [
            (s) => [s.results, s.filter],
            (results: PathResult, filter: Partial<FilterType>) => results?.filter || filter,
        ],
        propertiesForUrl: [
            (s) => [s.properties, s.filter],
            (properties: PropertyFilter[], filter: Partial<FilterType>) => {
                let result: Partial<FilterType> = {
                    insight: ViewType.PATHS,
                }
                if (properties && properties.length > 0) {
                    result['properties'] = properties
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
    actionToUrl: ({ values, props }) => ({
        setProperties: () => {
            if (!props.dashboardItemId) {
                return ['/insights', values.propertiesForUrl, undefined, { replace: true }]
            }
        },
        setFilter: () => {
            if (!props.dashboardItemId) {
                return ['/insights', values.propertiesForUrl, undefined, { replace: true }]
            }
        },
    }),
    urlToAction: ({ actions, values, key }) => ({
        '/insights': ({}, searchParams: Partial<FilterType>) => {
            if (searchParams.insight === ViewType.PATHS) {
                if (key != DEFAULT_PATH_LOGIC_KEY) {
                    return
                }
                const cleanedPathParams = cleanPathParams(searchParams)

                if (cleanedPathParams.funnel_filter && values.filter.date_from) {
                    cleanedPathParams.funnel_filter.date_from = values.filter.date_from
                }

                if (!objectsEqual(cleanedPathParams, values.filter)) {
                    actions.setFilter(cleanedPathParams)
                }

                if (!objectsEqual(searchParams.properties || [], values.properties)) {
                    actions.setProperties(searchParams.properties || [])
                }
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => actions.loadResults(),
    }),
})
