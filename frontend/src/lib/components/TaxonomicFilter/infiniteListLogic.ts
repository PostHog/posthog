import Fuse from 'fuse.js'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl } from 'kea-router'
import { RenderedRows } from 'react-virtualized/dist/es/List'

import api from 'lib/api'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { taxonomicFilterPreferencesLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterPreferencesLogic'
import {
    InfiniteListLogicProps,
    ListFuse,
    ListStorage,
    LoaderOptions,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { isEmail, isURL } from 'lib/utils'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { CohortType, EventDefinition } from '~/types'

import { teamLogic } from '../../../scenes/teamLogic'
import { captureTimeToSeeData } from '../../internalMetrics'
import { getItemGroup } from './InfiniteList'
import type { infiniteListLogicType } from './infiniteListLogicType'

/*
 by default the pop-up starts open for the first item in the list
 this can be used with actions.setIndex to allow a caller to override that
 */
export const NO_ITEM_SELECTED = -1

function appendAtIndex<T>(array: T[], items: any[], startIndex?: number): T[] {
    if (startIndex === undefined) {
        return [...array, ...items]
    }
    const arrayCopy = [...array]
    items.forEach((item, i) => {
        arrayCopy[startIndex + i] = item
    })
    return arrayCopy
}

const createEmptyListStorage = (searchQuery = '', first = false): ListStorage => ({
    results: [],
    searchQuery,
    count: 0,
    first,
})

// simple cache with a setTimeout expiry
const API_CACHE_TIMEOUT = 60000
let apiCache: Record<string, ListStorage> = {}
let apiCacheTimers: Record<string, number> = {}

async function fetchCachedListResponse(path: string, searchParams: Record<string, any>): Promise<ListStorage> {
    const url = combineUrl(path, searchParams).url
    let response
    if (apiCache[url]) {
        response = apiCache[url]
    } else {
        response = await api.get(url)
        apiCache[url] = response
        apiCacheTimers[url] = window.setTimeout(() => {
            delete apiCache[url]
            delete apiCacheTimers[url]
        }, API_CACHE_TIMEOUT)
    }
    return response
}

export const infiniteListLogic = kea<infiniteListLogicType>([
    props({ showNumericalPropsOnly: false } as InfiniteListLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}-${props.listGroupType}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'infiniteListLogic', key]),

    connect((props: InfiniteListLogicProps) => ({
        values: [
            taxonomicFilterLogic(props),
            ['searchQuery', 'value', 'groupType', 'taxonomicGroups'],
            teamLogic,
            ['currentTeamId'],
        ],
        actions: [
            taxonomicFilterLogic(props),
            ['setSearchQuery', 'selectItem', 'infiniteListResultsReceived'],
            taxonomicFilterPreferencesLogic,
            ['setEventOrdering'],
        ],
    })),
    actions({
        selectSelected: true,
        moveUp: true,
        moveDown: true,
        setIndex: (index: number) => ({ index }),
        setLimit: (limit: number) => ({ limit }),
        onRowsRendered: (rowInfo: RenderedRows) => ({ rowInfo }),
        loadRemoteItems: (options: LoaderOptions) => options,
        updateRemoteItem: (item: TaxonomicDefinitionTypes) => ({ item }),
        expand: true,
        abortAnyRunningQuery: true,
    }),
    loaders(({ actions, values, cache, props }) => ({
        remoteItems: [
            createEmptyListStorage('', true),
            {
                loadRemoteItems: async ({ offset, limit }, breakpoint) => {
                    if (!values.remoteItems.first) {
                        await breakpoint(500)
                    } else {
                        // These connected values below might be read before they are available due to circular logic mounting.
                        // Adding a slight delay (breakpoint) fixes this.
                        await breakpoint(1)
                    }

                    const {
                        isExpanded,
                        remoteEndpoint,
                        scopedRemoteEndpoint,
                        swappedInQuery,
                        searchQuery,
                        excludedProperties,
                        listGroupType,
                        propertyAllowList,
                    } = values

                    if (!remoteEndpoint) {
                        // should not have been here in the first place!
                        return createEmptyListStorage(swappedInQuery || searchQuery)
                    }

                    const searchParams = {
                        [`${values.group?.searchAlias || 'search'}`]: swappedInQuery || searchQuery,
                        limit,
                        offset,
                        excluded_properties:
                            excludedProperties && excludedProperties.length > 0
                                ? JSON.stringify(excludedProperties)
                                : undefined,
                        properties: propertyAllowList ? propertyAllowList.join(',') : undefined,
                        ...(props.showNumericalPropsOnly ? { is_numerical: 'true' } : {}),
                        // TODO: remove this filter once we can support behavioral cohorts for feature flags, it's only
                        // used in the feature flag property filter UI
                        ...(props.hideBehavioralCohorts ? { hide_behavioral_cohorts: 'true' } : {}),
                    }

                    const start = performance.now()
                    actions.abortAnyRunningQuery()

                    const [response, expandedCountResponse] = await Promise.all([
                        // get the list of results
                        fetchCachedListResponse(
                            scopedRemoteEndpoint && !isExpanded ? scopedRemoteEndpoint : remoteEndpoint,
                            searchParams
                        ),
                        // if this is an unexpanded scoped list, get the count for the full list
                        scopedRemoteEndpoint && !isExpanded
                            ? fetchCachedListResponse(remoteEndpoint, {
                                  ...searchParams,
                                  limit: 1,
                                  offset: 0,
                              })
                            : null,
                    ])
                    breakpoint()

                    const queryChanged = values.remoteItems.searchQuery !== (swappedInQuery || searchQuery)

                    await captureTimeToSeeData(values.currentTeamId, {
                        type: 'properties_load',
                        context: 'filters',
                        action: listGroupType,
                        primary_interaction_id: '',
                        status: 'success',
                        time_to_see_data_ms: Math.floor(performance.now() - start),
                        api_response_bytes: 0,
                    })
                    cache.abortController = null

                    return {
                        results: appendAtIndex(
                            queryChanged ? [] : values.remoteItems.results,
                            response.results || response,
                            offset
                        ),
                        searchQuery: swappedInQuery || searchQuery,
                        originalQuery: swappedInQuery ? searchQuery : undefined,
                        queryChanged,
                        count:
                            response.count ||
                            (Array.isArray(response) ? response.length : 0) ||
                            (response.results || []).length,
                        expandedCount: expandedCountResponse?.count,
                    }
                },
                updateRemoteItem: ({ item }) => {
                    // On updating item, invalidate cache
                    apiCache = {}
                    apiCacheTimers = {}
                    const popFromResults = 'hidden' in item && item.hidden
                    const results: TaxonomicDefinitionTypes[] = values.remoteItems.results
                        .map((i) => (i.name === item.name ? (popFromResults ? null : item) : i))
                        .filter((i): i is TaxonomicDefinitionTypes => i !== null)
                    return {
                        ...values.remoteItems,
                        results,
                    }
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        /**
         * In some circumstances we want to swap out the query that is sent to the backend.
         * The canonical example is if you search for a URL, then we swap in $current URL,
         * since that's almost certainly what you want
         */
        swappedInQuery: [
            null as string | null,
            {
                setSearchQuery: (_, { searchQuery }) => {
                    if (props.listGroupType === TaxonomicFilterGroupType.EventProperties && isURL(searchQuery)) {
                        return '$current_url'
                    }
                    // TODO not everyone will call this email 🤷
                    // but this is an obvious option to add
                    if (props.listGroupType === TaxonomicFilterGroupType.PersonProperties && isEmail(searchQuery)) {
                        return 'email'
                    }
                    return null
                },
            },
        ],
        index: [
            (props.selectFirstItem === false || props.autoSelectItem === false ? NO_ITEM_SELECTED : 0) as number,
            {
                setIndex: (_, { index }) => index,
                loadRemoteItemsSuccess: (state, { remoteItems }) =>
                    remoteItems.queryChanged ? (props.autoSelectItem === false ? NO_ITEM_SELECTED : 0) : state,
            },
        ],
        showPopover: [props.popoverEnabled !== false, {}],
        limit: [
            100,
            {
                setLimit: (_, { limit }) => limit,
            },
        ],
        startIndex: [0, { onRowsRendered: (_, { rowInfo: { startIndex } }) => startIndex }],
        stopIndex: [0, { onRowsRendered: (_, { rowInfo: { stopIndex } }) => stopIndex }],
        isExpanded: [false, { expand: () => true }],
    })),
    selectors({
        listGroupType: [(_, p) => [p.listGroupType], (listGroupType) => listGroupType],
        allowNonCapturedEvents: [
            () => [(_, props) => props.allowNonCapturedEvents],
            (allowNonCapturedEvents: boolean | undefined) => allowNonCapturedEvents ?? false,
        ],
        isLoading: [(s) => [s.remoteItemsLoading], (remoteItemsLoading) => remoteItemsLoading],
        group: [
            (s) => [s.listGroupType, s.taxonomicGroups],
            (listGroupType, taxonomicGroups): TaxonomicFilterGroup =>
                taxonomicGroups.find((g) => g.type === listGroupType) as TaxonomicFilterGroup,
        ],
        remoteEndpoint: [(s) => [s.group], (group) => group?.endpoint || null],
        excludedProperties: [(s) => [s.group], (group) => group?.excludedProperties],
        propertyAllowList: [(s) => [s.group], (group) => group?.propertyAllowList],
        scopedRemoteEndpoint: [(s) => [s.group], (group) => group?.scopedEndpoint || null],
        hasRenderFunction: [(s) => [s.group], (group) => !!group?.render],
        isExpandable: [
            (s) => [s.remoteEndpoint, s.scopedRemoteEndpoint, s.remoteItems],
            (remoteEndpoint, scopedRemoteEndpoint, remoteItems) =>
                !!(
                    remoteEndpoint &&
                    scopedRemoteEndpoint &&
                    remoteItems.expandedCount &&
                    remoteItems.expandedCount > remoteItems.count
                ),
        ],
        isExpandableButtonSelected: [
            (s) => [s.isExpandable, s.index, s.totalListCount],
            (isExpandable, index, totalListCount) => isExpandable && index === totalListCount - 1,
        ],
        hasRemoteDataSource: [(s) => [s.remoteEndpoint], (remoteEndpoint) => !!remoteEndpoint],
        rawLocalItems: [
            (selectors) => [
                (state, props: InfiniteListLogicProps) => {
                    const taxonomicGroups = selectors.taxonomicGroups(state)
                    const group = taxonomicGroups.find((g) => g.type === props.listGroupType)

                    if (group?.logic && group?.value) {
                        let items = group.logic.selectors[group.value]?.(state)

                        // Handle paginated responses for cohorts, which return a CountedPaginatedResponse
                        if (items?.results) {
                            items = items.results
                        }

                        return items
                    }
                    if (group?.options) {
                        return group.options
                    }
                    if (props.optionsFromProp && Object.keys(props.optionsFromProp).includes(props.listGroupType)) {
                        return props.optionsFromProp[props.listGroupType]
                    }
                    return null
                },
            ],
            (rawLocalItems: (EventDefinition | CohortType)[]) => rawLocalItems,
        ],
        fuse: [
            (s) => [s.rawLocalItems, s.taxonomicGroups, s.group],
            (rawLocalItems, taxonomicGroups, group): ListFuse => {
                // maps e.g. "selector" to its display value "CSS Selector"
                // so a search of "css" matches something
                function asPostHogName(
                    g: TaxonomicFilterGroup,
                    item: EventDefinition | CohortType
                ): string | undefined {
                    return g ? getCoreFilterDefinition(g.getName?.(item), g.type)?.label : undefined
                }

                const haystack = (rawLocalItems || []).map((item) => {
                    const itemGroup = getItemGroup(item, taxonomicGroups, group)
                    return {
                        name: itemGroup?.getName?.(item) || '',
                        posthogName: asPostHogName(itemGroup, item),
                        item: item,
                    }
                })

                return new Fuse(haystack, {
                    keys: ['name', 'posthogName'],
                    threshold: 0.3,
                })
            },
        ],
        localItems: [
            (s) => [s.rawLocalItems, s.searchQuery, s.swappedInQuery, s.fuse, s.group],
            (rawLocalItems, searchQuery, swappedInQuery, fuse, group): ListStorage => {
                if (group.localItemsSearch) {
                    const filtered = group.localItemsSearch(rawLocalItems || [], swappedInQuery || searchQuery)
                    return {
                        results: filtered,
                        count: filtered.length,
                        searchQuery: swappedInQuery || searchQuery,
                        originalQuery: swappedInQuery ? searchQuery : undefined,
                    }
                }

                if (rawLocalItems) {
                    const filteredItems =
                        swappedInQuery || searchQuery
                            ? fuse.search(swappedInQuery || searchQuery).map((result) => result.item.item)
                            : rawLocalItems

                    return {
                        results: filteredItems,
                        count: filteredItems.length,
                        searchQuery: swappedInQuery || searchQuery,
                        originalQuery: swappedInQuery ? searchQuery : undefined,
                    }
                }
                return createEmptyListStorage()
            },
        ],
        items: [
            (s) => [s.remoteItems, s.localItems],
            (remoteItems, localItems) => {
                return {
                    results: [...localItems.results, ...remoteItems.results],
                    count: localItems.count + remoteItems.count,
                    searchQuery: remoteItems.searchQuery || localItems.searchQuery,
                    originalQuery: remoteItems.originalQuery || localItems.originalQuery,
                    expandedCount: remoteItems.expandedCount,
                    queryChanged: remoteItems.queryChanged,
                    first: localItems.first && remoteItems.first,
                }
            },
        ],
        totalResultCount: [(s) => [s.items], (items) => items.count || 0],
        totalExtraCount: [
            (s) => [s.isExpandable, s.hasRenderFunction],
            (isExpandable, hasRenderFunction) => (isExpandable ? 1 : 0) + (hasRenderFunction ? 1 : 0),
        ],
        totalListCount: [
            (s) => [s.totalResultCount, s.totalExtraCount],
            (totalResultCount, totalExtraCount) => totalResultCount + totalExtraCount,
        ],
        expandedCount: [(s) => [s.items], (items) => items.expandedCount || 0],
        results: [(s) => [s.items], (items) => items.results],
        selectedItem: [
            (s) => [s.index, s.items],
            (index, items): TaxonomicDefinitionTypes | undefined => (index >= 0 ? items.results[index] : undefined),
        ],
        selectedItemValue: [
            (s) => [s.selectedItem, s.group],
            (selectedItem, group) => (selectedItem ? group?.getValue?.(selectedItem) || null : null),
        ],
        selectedItemInView: [
            (s) => [s.index, s.startIndex, s.stopIndex],
            (index, startIndex, stopIndex) => typeof index === 'number' && index >= startIndex && index <= stopIndex,
        ],
    }),
    listeners(({ values, actions, props, cache }) => ({
        onRowsRendered: ({ rowInfo: { startIndex, stopIndex, overscanStopIndex } }) => {
            if (values.hasRemoteDataSource) {
                let loadFrom: number | null = null
                for (let i = startIndex; i < (stopIndex + overscanStopIndex) / 2; i++) {
                    if (!values.results[i]) {
                        loadFrom = i
                        break
                    }
                }
                if (loadFrom !== null) {
                    const offset = (loadFrom || startIndex) - values.localItems.count
                    actions.loadRemoteItems({ offset, limit: values.limit })
                }
            }
        },
        setSearchQuery: async () => {
            if (values.hasRemoteDataSource) {
                actions.loadRemoteItems({ offset: 0, limit: values.limit })
            } else if (props.autoSelectItem) {
                actions.setIndex(0)
            }
        },
        setEventOrdering: async () => {
            if (props.listGroupType !== TaxonomicFilterGroupType.Events) {
                return
            }

            if (values.hasRemoteDataSource) {
                actions.loadRemoteItems({ offset: 0, limit: values.limit })
            } else if (props.autoSelectItem) {
                actions.setIndex(0)
            }
        },
        moveUp: () => {
            const { index, totalListCount } = values
            actions.setIndex((index - 1 + totalListCount) % totalListCount)
        },
        moveDown: () => {
            const { index, totalListCount } = values
            actions.setIndex((index + 1) % totalListCount)
        },
        selectSelected: () => {
            if (values.isExpandableButtonSelected) {
                actions.expand()
            } else {
                actions.selectItem(
                    values.group,
                    values.selectedItemValue,
                    values.selectedItem,
                    values.swappedInQuery ? values.searchQuery : undefined
                )
            }
        },
        loadRemoteItemsSuccess: ({ remoteItems }) => {
            actions.infiniteListResultsReceived(props.listGroupType, remoteItems)
        },
        expand: () => {
            actions.loadRemoteItems({ offset: values.index, limit: values.limit })
        },
        abortAnyRunningQuery: () => {
            // Remove any existing abort controller
            cache.disposables.dispose('abortController')

            // Add new abort controller
            cache.disposables.add(() => {
                const abortController = new AbortController()
                // Store reference in cache for the fetch operation to use
                cache.abortController = abortController
                return () => abortController.abort()
            }, 'abortController')
        },
    })),
    events(({ actions, values, props, cache }) => ({
        afterMount: () => {
            if (values.hasRemoteDataSource) {
                actions.loadRemoteItems({ offset: 0, limit: values.limit })
            } else if (values.groupType === props.listGroupType) {
                const { value, group, results } = values
                actions.setIndex(results.findIndex((r) => group?.getValue?.(r) === value))
            }

            // Clean up all cache timers to prevent memory leaks
            cache.disposables.add(() => {
                return () => {
                    Object.values(apiCacheTimers).forEach((timerId) => {
                        window.clearTimeout(timerId)
                    })
                }
            }, 'apiCacheTimersCleanup')
        },
    })),

    // Note: API cache timers are automatically cleaned up by the disposables plugin (configured in afterMount)
])
