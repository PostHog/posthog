import { kea } from 'kea'
import { objectsEqual, uuid } from 'lib/utils'
import api from 'lib/api'
import { combineUrl, encodeParams, router } from 'kea-router'
import { insightLogic } from 'scenes/insights/insightLogic'
import { pathsLogicType } from './pathsLogicType'
import { InsightLogicProps, FilterType, PathType, PropertyFilter, ViewType } from '~/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'

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

export const pathsLogic = kea<pathsLogicType<PathNode, PathResult>>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_PATH_LOGIC_KEY),

    actions: {
        setProperties: (properties) => ({ properties }),
        setFilter: (filter: Partial<FilterType>) => ({ filter }),
        setCachedResults: (filters: Partial<FilterType>, results: any) => ({ filters, results }),
        showPathEvents: (event) => ({ event }),
        updateExclusions: (exclusions: string[]) => ({ exclusions }),
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
                const dashboardItemId = props.dashboardItemId
                insightLogic(props).actions.startQuery(queryId)
                if (dashboardItemId) {
                    dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, true, null)
                }

                let paths
                try {
                    paths = await api.create(`api/insight/path`, params)
                } catch (e) {
                    breakpoint()
                    insightLogic(props).actions.endQuery(queryId, ViewType.PATHS, null, e)
                    if (dashboardItemId) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, null)
                    }

                    return { paths: [], filter, error: true }
                }
                breakpoint()
                insightLogic(props).actions.endQuery(queryId, ViewType.PATHS, paths.last_refresh)
                if (dashboardItemId) {
                    dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, paths.last_refresh)
                }

                return { paths: paths.result, filter }
            },
        },
    }),
    reducers: ({ props }) => ({
        filter: [
            (state: Record<string, any>) => cleanFilters(props.filters || router.selectors.searchParams(state)),
            {
                setFilter: (state, { filter }) => ({ ...state, ...filter }),
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
            insightLogic(props).actions.setFilters({
                ...cleanFilters(values.filter),
                properties: values.properties,
            })
            actions.loadResults(true)
        },
        loadResultsSuccess: async () => {
            insightLogic(props).actions.fetchedResults({
                ...cleanFilters(values.filter),
                properties: values.properties,
            })
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
            if (props.syncWithUrl) {
                return ['/insights', values.propertiesForUrl, undefined, { replace: true }]
            }
        },
        setFilter: () => {
            if (props.syncWithUrl) {
                return ['/insights', values.propertiesForUrl, undefined, { replace: true }]
            }
        },
    }),
    urlToAction: ({ actions, values, props }) => ({
        '/insights': ({}, searchParams: Partial<FilterType>) => {
            if (props.syncWithUrl && searchParams.insight === ViewType.PATHS) {
                const cleanedPathParams = cleanFilters(searchParams)

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
