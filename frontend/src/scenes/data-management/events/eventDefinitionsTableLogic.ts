import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api, { PaginatedResponse } from 'lib/api'
import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import { EVENT_DEFINITIONS_PER_PAGE, PROPERTY_DEFINITIONS_PER_EVENT } from 'lib/constants'
import { objectsEqual } from 'lib/utils/objects'
import { truncate } from 'lib/utils/strings'
import { parseTagsFilter } from 'lib/utils/url'
import { projectLogic } from 'scenes/projectLogic'

import { AnyPropertyFilter, EventDefinition, EventDefinitionType, JsonType, PropertyDefinition } from '~/types'

import {
    eventDefinitionsBulkUpdateHiddenCreate,
    eventDefinitionsBulkUpdateVerifiedCreate,
} from 'products/event_definitions/frontend/generated/api'
import type {
    EventDefinitionBulkUpdateHiddenResponseApi,
    EventDefinitionBulkUpdateVerifiedResponseApi,
    PaginatedEnterpriseEventDefinitionListApi,
} from 'products/event_definitions/frontend/generated/api.schemas'

import type {
    BulkUpdateTagsUUIDErrorApi,
    EventDefinitionBulkUpdateHiddenItemApi,
    EventDefinitionBulkUpdateVerifiedItemApi,
} from '../../../../../products/event_definitions/frontend/generated/api.schemas'

export interface EventDefinitionsPaginatedResponse
    extends PaginatedResponse<EventDefinition>, Pick<PaginatedEnterpriseEventDefinitionListApi, 'count_is_capped'> {
    current?: string
    count?: number
    page?: number
}

export interface PropertyDefinitionsPaginatedResponse extends PaginatedResponse<PropertyDefinition> {
    current?: string
    count?: number
    page?: number
}

export interface Filters {
    event: string
    properties: AnyPropertyFilter[]
    event_type: EventDefinitionType
    ordering?: string
    tags?: string[]
    verified?: boolean
}

export interface BulkVerifiedResult extends EventDefinitionBulkUpdateVerifiedResponseApi {
    // Echoes the requested target so the success toast can describe the direction (verify vs unverify).
    verified: boolean
}

export interface BulkHiddenResult extends EventDefinitionBulkUpdateHiddenResponseApi {
    // Echoes the requested target so the success toast can describe the direction (hide vs unhide).
    hidden: boolean
}

const DEFAULT_FILTERS: Filters = {
    event: '',
    properties: [],
    event_type: EventDefinitionType.Event,
    ordering: 'event',
    tags: undefined,
    verified: undefined,
}

// Event properties are untrusted input of any size, so the example is capped before the table renders it.
const MAX_PROPERTY_EXAMPLE_LENGTH = 200

function formatPropertyExample(value: JsonType | undefined): string | undefined {
    if (value === undefined) {
        return undefined
    }
    try {
        return truncate(JSON.stringify(value), MAX_PROPERTY_EXAMPLE_LENGTH)
    } catch {
        return undefined
    }
}

export function createDefinitionKey(event?: EventDefinition, property?: PropertyDefinition): string {
    return `${event?.id ?? 'event'}-${property?.id ?? 'property'}`
}

export function normalizePropertyDefinitionEndpointUrl(
    url: string | null | undefined,
    searchParams: Record<string, any> = {},
    full: boolean = false
): string | null {
    if (!full && !url) {
        return null
    }
    return api.propertyDefinitions.determineListEndpoint({
        ...(url ? combineUrl(url).searchParams : {}),
        ...searchParams,
    })
}

/**
 * Patches the page a bulk request started on, not whatever is current now: the user may have
 * navigated while it was in flight. Returns the value the eventDefinitions reducer should hold.
 */
function patchPinnedPage(
    cache: Record<string, any>,
    cacheKey: string | undefined,
    current: EventDefinitionsPaginatedResponse,
    patchDefinition: (definition: EventDefinition) => EventDefinition
): EventDefinitionsPaginatedResponse {
    if (!cacheKey) {
        return current
    }
    const onScreen = current.current === cacheKey
    const source: EventDefinitionsPaginatedResponse | undefined =
        cache.apiCache?.[cacheKey] ?? (onScreen ? current : undefined)
    if (!source) {
        return current
    }
    const patched = { ...source, results: source.results.map(patchDefinition) }
    cache.apiCache = { ...cache.apiCache, [cacheKey]: patched }
    // Only replace what's on screen if it's still that same page.
    return onScreen ? patched : current
}

function toastBulkResult(doneLabel: string, updatedCount: number, skippedCount: number): void {
    if (updatedCount > 0) {
        lemonToast.success(`${doneLabel} ${updatedCount} event${updatedCount !== 1 ? 's' : ''}`)
    }
    if (skippedCount > 0) {
        lemonToast.warning(`${skippedCount} event${skippedCount !== 1 ? 's' : ''} skipped`)
    }
    if (updatedCount === 0 && skippedCount === 0) {
        lemonToast.info('No events needed updating')
    }
}

function filtersFromSearchParams(searchParams: Record<string, any>): Filters {
    const { event, event_type, ordering, tags, verified } = searchParams
    return {
        ...DEFAULT_FILTERS,
        ...(event !== undefined && { event }),
        ...(event_type !== undefined && { event_type }),
        ...(ordering !== undefined && { ordering }),
        ...(parseTagsFilter(tags) !== undefined && { tags: parseTagsFilter(tags) }),
        ...(verified !== undefined && { verified: verified === 'true' || verified === true }),
    }
}

function normalizeEventDefinitionEndpointUrl({
    url,
    searchParams = {},
    full = false,
    eventTypeFilter = EventDefinitionType.Event,
}: {
    url?: string | null | undefined
    searchParams?: Record<string, any>
    full?: boolean
    eventTypeFilter?: EventDefinitionType
}): string | null {
    if (!full && !url) {
        return null
    }
    const params = {
        ...(url
            ? {
                  ...combineUrl(url).searchParams,
                  event_type: eventTypeFilter,
              }
            : {}),
        ...searchParams,
    }
    return api.eventDefinitions.determineListEndpoint(params)
}

export interface EventDefinitionsTableLogicProps {
    key: string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface eventDefinitionsTableLogicValues {
    currentProjectId: number | null // projectLogic
    bulkEditLoading: boolean
    bulkHiddenResult: BulkHiddenResult | null
    bulkHiddenResultLoading: boolean
    bulkVerifiedResult: BulkVerifiedResult | null
    bulkVerifiedResultLoading: boolean
    eventDefinitionPropertiesLoading: string[]
    eventDefinitions: EventDefinitionsPaginatedResponse
    eventDefinitionsLoading: boolean
    eventPropertiesCacheMap: Record<string, PropertyDefinitionsPaginatedResponse>
    eventPropertiesCacheMapLoading: boolean
    filters: Filters
    paramsFromFilters: Record<string, any>
    showVerifiedFilter: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface eventDefinitionsTableLogicActions {
    applyBulkHiddenUpdates: (
        updates: {
            hidden: boolean
            id: string
        }[]
    ) => {
        updates: {
            hidden: boolean
            id: string
        }[]
    }
    applyBulkHiddenUpdatesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    applyBulkHiddenUpdatesSuccess: (
        eventDefinitions: EventDefinitionsPaginatedResponse,
        payload?: {
            updates: {
                hidden: boolean
                id: string
            }[]
        }
    ) => {
        eventDefinitions: EventDefinitionsPaginatedResponse
        payload?: {
            updates: {
                hidden: boolean
                id: string
            }[]
        }
    }
    applyBulkTagUpdates: (
        updates: {
            id: number | string
            tags: string[]
        }[]
    ) => {
        updates: {
            id: number | string
            tags: string[]
        }[]
    }
    applyBulkTagUpdatesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    applyBulkTagUpdatesSuccess: (
        eventDefinitions: EventDefinitionsPaginatedResponse,
        payload?: {
            updates: {
                id: number | string
                tags: string[]
            }[]
        }
    ) => {
        eventDefinitions: EventDefinitionsPaginatedResponse
        payload?: {
            updates: {
                id: number | string
                tags: string[]
            }[]
        }
    }
    applyBulkVerifiedUpdates: (
        updates: {
            id: string
            verified: boolean
        }[]
    ) => {
        updates: {
            id: string
            verified: boolean
        }[]
    }
    applyBulkVerifiedUpdatesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    applyBulkVerifiedUpdatesSuccess: (
        eventDefinitions: EventDefinitionsPaginatedResponse,
        payload?: {
            updates: {
                id: string
                verified: boolean
            }[]
        }
    ) => {
        eventDefinitions: EventDefinitionsPaginatedResponse
        payload?: {
            updates: {
                id: string
                verified: boolean
            }[]
        }
    }
    bulkUpdateHidden: ({ ids, hidden }: { hidden: boolean; ids: string[]; onSuccess?: () => void }) => {
        ids: string[]
        hidden: boolean
        onSuccess?: () => void
    }
    bulkUpdateHiddenFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    bulkUpdateHiddenSuccess: (
        bulkHiddenResult: {
            hidden: boolean
            skipped: BulkUpdateTagsUUIDErrorApi[]
            updated: EventDefinitionBulkUpdateHiddenItemApi[]
        },
        payload?: {
            ids: string[]
            hidden: boolean
            onSuccess?: () => void
        }
    ) => {
        bulkHiddenResult: {
            hidden: boolean
            skipped: BulkUpdateTagsUUIDErrorApi[]
            updated: EventDefinitionBulkUpdateHiddenItemApi[]
        }
        payload?: {
            ids: string[]
            hidden: boolean
            onSuccess?: () => void
        }
    }
    bulkUpdateVerified: ({ ids, verified }: { ids: string[]; onSuccess?: () => void; verified: boolean }) => {
        ids: string[]
        verified: boolean
        onSuccess?: () => void
    }
    bulkUpdateVerifiedFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    bulkUpdateVerifiedSuccess: (
        bulkVerifiedResult: {
            skipped: BulkUpdateTagsUUIDErrorApi[]
            updated: EventDefinitionBulkUpdateVerifiedItemApi[]
            verified: boolean
        },
        payload?: {
            ids: string[]
            verified: boolean
            onSuccess?: () => void
        }
    ) => {
        bulkVerifiedResult: {
            skipped: BulkUpdateTagsUUIDErrorApi[]
            updated: EventDefinitionBulkUpdateVerifiedItemApi[]
            verified: boolean
        }
        payload?: {
            ids: string[]
            verified: boolean
            onSuccess?: () => void
        }
    }
    loadEventDefinitions: (url?: string | null) => {
        url: string | null
    }
    loadEventDefinitionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadEventDefinitionsSuccess: (
        eventDefinitions: EventDefinitionsPaginatedResponse,
        payload?: {
            url: string | null
        }
    ) => {
        eventDefinitions: EventDefinitionsPaginatedResponse
        payload?: {
            url: string | null
        }
    }
    loadEventExample: (definition: EventDefinition) => {
        definition: EventDefinition
    }
    loadPropertiesForEvent: (
        definition: EventDefinition,
        url?: string | null
    ) => {
        definition: EventDefinition
        url: string | null
    }
    loadPropertiesForEventFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPropertiesForEventSuccess: (
        eventPropertiesCacheMap: {
            [x: string]: any
        },
        payload?: {
            definition: EventDefinition
            url: string | null
        }
    ) => {
        eventPropertiesCacheMap: {
            [x: string]: any
        }
        payload?: {
            definition: EventDefinition
            url: string | null
        }
    }
    setEventDefinitionPropertiesLoading: (ids: string[]) => {
        ids: string[]
    }
    setFilters: (
        filters: Partial<Filters>,
        debounce?: boolean
    ) => {
        debounce: boolean
        filters: Partial<Filters>
    }
    setLocalEventDefinition: (definition: EventDefinition) => {
        definition: EventDefinition
    }
    setLocalEventDefinitionFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    setLocalEventDefinitionSuccess: (
        eventDefinitions: EventDefinitionsPaginatedResponse,
        payload?: {
            definition: EventDefinition
        }
    ) => {
        eventDefinitions: EventDefinitionsPaginatedResponse
        payload?: {
            definition: EventDefinition
        }
    }
    setLocalPropertyDefinition: (
        event: EventDefinition,
        definition: PropertyDefinition
    ) => {
        definition: PropertyDefinition
        event: EventDefinition
    }
    setLocalPropertyDefinitionFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    setLocalPropertyDefinitionSuccess: (
        eventPropertiesCacheMap: Record<string, PropertyDefinitionsPaginatedResponse>,
        payload?: {
            definition: PropertyDefinition
            event: EventDefinition
        }
    ) => {
        eventPropertiesCacheMap: Record<string, PropertyDefinitionsPaginatedResponse>
        payload?: {
            definition: PropertyDefinition
            event: EventDefinition
        }
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface eventDefinitionsTableLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        showVerifiedFilter: (eventDefinitions: EventDefinitionsPaginatedResponse, filters: Filters) => boolean
        bulkEditLoading: (bulkVerifiedResultLoading: boolean, bulkHiddenResultLoading: boolean) => boolean
        paramsFromFilters: (filters: Filters) => Record<string, any>
    }
}

export type eventDefinitionsTableLogicType = MakeLogicType<
    eventDefinitionsTableLogicValues,
    eventDefinitionsTableLogicActions,
    EventDefinitionsTableLogicProps,
    eventDefinitionsTableLogicMeta
>

export const eventDefinitionsTableLogic = kea<eventDefinitionsTableLogicType>([
    path((key) => ['scenes', 'data-management', 'events', 'eventDefinitionsTableLogic', key]),
    props({} as EventDefinitionsTableLogicProps),
    key((props) => props.key || 'scene'),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        loadEventDefinitions: (url: string | null = '') => ({ url }),
        loadEventExample: (definition: EventDefinition) => ({ definition }),
        loadPropertiesForEvent: (definition: EventDefinition, url: string | null = '') => ({ definition, url }),
        setFilters: (filters: Partial<Filters>, debounce: boolean = true) => ({ filters, debounce }),
        setLocalEventDefinition: (definition: EventDefinition) => ({ definition }),
        applyBulkTagUpdates: (updates: { id: number | string; tags: string[] }[]) => ({ updates }),
        applyBulkVerifiedUpdates: (updates: { id: string; verified: boolean }[]) => ({ updates }),
        applyBulkHiddenUpdates: (updates: { id: string; hidden: boolean }[]) => ({ updates }),
        setLocalPropertyDefinition: (event: EventDefinition, definition: PropertyDefinition) => ({ event, definition }),
        setEventDefinitionPropertiesLoading: (ids: string[]) => ({ ids }),
    }),
    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                    properties: convertPropertyGroupToProperties(filters.properties) ?? [],
                }),
            },
        ],
        eventDefinitionPropertiesLoading: [
            [] as string[],
            {
                setEventDefinitionPropertiesLoading: (_, { ids }) => ids ?? [],
            },
        ],
    }),
    loaders(({ values, cache, actions }) => ({
        eventDefinitions: [
            {
                count: 0,
                next: undefined,
                current: undefined,
                previous: undefined,
                results: [],
            } as EventDefinitionsPaginatedResponse,
            {
                loadEventDefinitions: async ({ url: _url }, breakpoint) => {
                    let url = _url

                    if (!url) {
                        url = api.eventDefinitions.determineListEndpoint(values.paramsFromFilters)
                    }

                    if (url && url in (cache.apiCache ?? {})) {
                        return cache.apiCache[url]
                    }

                    cache.eventsStartTime = performance.now()
                    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a URL built at runtime and an unchecked response type. Use a generated function if one covers this endpoint.
                    const response = await api.get(url)
                    breakpoint()

                    const result = {
                        ...response,
                        previous: normalizeEventDefinitionEndpointUrl({
                            url: response.previous,
                            eventTypeFilter: values.filters.event_type,
                        }),
                        next: normalizeEventDefinitionEndpointUrl({
                            url: response.next,
                            eventTypeFilter: values.filters.event_type,
                        }),
                        current: url,
                        page: Math.floor((combineUrl(url).searchParams.offset ?? 0) / EVENT_DEFINITIONS_PER_PAGE) + 1,
                    }

                    cache.apiCache = {
                        ...cache.apiCache,
                        [url]: result,
                    }

                    return result
                },
                setLocalEventDefinition: ({ definition }) => {
                    if (!values.eventDefinitions.current) {
                        return values.eventDefinitions
                    }
                    const result = {
                        ...values.eventDefinitions,
                        results: values.eventDefinitions.results.map((d) => (d.id === definition.id ? definition : d)),
                    }

                    // Update cache
                    cache.apiCache = {
                        ...cache.apiCache,
                        [values.eventDefinitions.current]: result,
                    }

                    return result
                },
                applyBulkTagUpdates: ({ updates }) => {
                    if (!values.eventDefinitions.current || updates.length === 0) {
                        return values.eventDefinitions
                    }
                    const tagsById = new Map(updates.map((u) => [String(u.id), u.tags]))
                    const result = {
                        ...values.eventDefinitions,
                        results: values.eventDefinitions.results.map((d) =>
                            tagsById.has(String(d.id)) ? { ...d, tags: tagsById.get(String(d.id)) } : d
                        ),
                    }

                    cache.apiCache = {
                        ...cache.apiCache,
                        [values.eventDefinitions.current]: result,
                    }

                    return result
                },
                applyBulkVerifiedUpdates: ({ updates }) => {
                    if (updates.length === 0) {
                        return values.eventDefinitions
                    }
                    const verifiedById = new Map(updates.map((u) => [String(u.id), u.verified] as const))
                    return patchPinnedPage(cache, cache.bulkVerifiedCacheKey, values.eventDefinitions, (d) => {
                        const verified = verifiedById.get(String(d.id))
                        if (verified === undefined) {
                            return d
                        }
                        // Like the server, verifying also unhides the event and cancels a scheduled delete
                        return verified
                            ? { ...d, verified, hidden: false, scheduled_deletion_at: null }
                            : { ...d, verified }
                    })
                },
                applyBulkHiddenUpdates: ({ updates }) => {
                    if (updates.length === 0) {
                        return values.eventDefinitions
                    }
                    const hiddenById = new Map(updates.map((u) => [String(u.id), u.hidden] as const))
                    return patchPinnedPage(cache, cache.bulkHiddenCacheKey, values.eventDefinitions, (d) => {
                        const hidden = hiddenById.get(String(d.id))
                        if (hidden === undefined) {
                            return d
                        }
                        // Like the server, hiding also unverifies the event and unhiding cancels a scheduled delete
                        return hidden
                            ? { ...d, hidden, verified: false }
                            : { ...d, hidden, scheduled_deletion_at: null }
                    })
                },
            },
        ],
        bulkVerifiedResult: [
            null as BulkVerifiedResult | null,
            {
                bulkUpdateVerified: async ({
                    ids,
                    verified,
                }: {
                    ids: string[]
                    verified: boolean
                    onSuccess?: () => void
                }) => {
                    // Pin the page being edited now: the user may page or filter away before the
                    // request resolves, and the row patch must land on the page it started on.
                    cache.bulkVerifiedCacheKey = values.eventDefinitions.current
                    const response = await eventDefinitionsBulkUpdateVerifiedCreate(String(values.currentProjectId), {
                        ids,
                        verified,
                    })
                    return { verified, ...response }
                },
            },
        ],
        bulkHiddenResult: [
            null as BulkHiddenResult | null,
            {
                bulkUpdateHidden: async ({
                    ids,
                    hidden,
                }: {
                    ids: string[]
                    hidden: boolean
                    onSuccess?: () => void
                }) => {
                    cache.bulkHiddenCacheKey = values.eventDefinitions.current
                    const response = await eventDefinitionsBulkUpdateHiddenCreate(String(values.currentProjectId), {
                        ids,
                        hidden,
                    })
                    return { hidden, ...response }
                },
            },
        ],
        eventPropertiesCacheMap: [
            {} as Record<string, PropertyDefinitionsPaginatedResponse>,
            {
                loadPropertiesForEvent: async ({ definition, url }, breakpoint) => {
                    if (url && url in (cache.apiCache ?? {})) {
                        return {
                            ...values.eventPropertiesCacheMap,
                            [definition.id]: cache.apiCache[url],
                        }
                    }

                    if (!url) {
                        url = api.propertyDefinitions.determineListEndpoint({
                            event_names: [definition.name],
                            exclude_core_properties: true,
                            filter_by_event_names: true,
                            is_feature_flag: false,
                            limit: PROPERTY_DEFINITIONS_PER_EVENT,
                        })
                    }
                    actions.setEventDefinitionPropertiesLoading(
                        Array.from([...values.eventDefinitionPropertiesLoading, definition.id])
                    )
                    cache.propertiesStartTime = performance.now()
                    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a URL built at runtime and an unchecked response type. Use a generated function if one covers this endpoint.
                    const response = await api.get(url)
                    breakpoint()

                    // Fetch one event as example and cache (only if events have been captured)
                    let exampleEventProperties: Record<string, JsonType> = {}
                    if (definition.last_seen_at) {
                        const exampleUrl = api.events.determineListEndpoint({ event: definition.name }, 1)
                        if (exampleUrl && exampleUrl in (cache.apiCache ?? {})) {
                            exampleEventProperties = cache.apiCache[exampleUrl]
                        } else {
                            // nosemgrep: prefer-codegen-api -- Legacy raw API call with a URL built at runtime and an unchecked response type. Use a generated function if one covers this endpoint.
                            exampleEventProperties = (await api.get(exampleUrl))?.results?.[0].properties ?? {}
                            cache.apiCache = {
                                ...cache.apiCache,
                                [exampleUrl]: exampleEventProperties,
                            }
                        }
                    }

                    const currentUrl = `${normalizePropertyDefinitionEndpointUrl(url)}`
                    const propertyResult = {
                        count: response.count,
                        previous: normalizePropertyDefinitionEndpointUrl(response.previous),
                        next: normalizePropertyDefinitionEndpointUrl(response.next),
                        current: currentUrl,
                        page:
                            Math.floor(
                                (combineUrl(currentUrl).searchParams.offset ?? 0) / PROPERTY_DEFINITIONS_PER_EVENT
                            ) + 1,
                        results: response.results.map((prop: PropertyDefinition) => ({
                            ...prop,
                            example: formatPropertyExample(exampleEventProperties?.[prop.name]),
                        })),
                    }

                    cache.apiCache = {
                        ...cache.apiCache,
                        [currentUrl]: propertyResult,
                    }

                    actions.setEventDefinitionPropertiesLoading(
                        values.eventDefinitionPropertiesLoading.filter((loadingId) => loadingId != definition.id)
                    )
                    return {
                        ...values.eventPropertiesCacheMap,
                        [definition.id]: propertyResult,
                    }
                },
                setLocalPropertyDefinition: ({ event, definition }) => {
                    if (!values.eventPropertiesCacheMap?.[event.id]?.current) {
                        return values.eventPropertiesCacheMap
                    }
                    // Update cache as well
                    const eventCacheKey = values.eventPropertiesCacheMap[event.id].current as string
                    const updatedProperties = {
                        ...values.eventPropertiesCacheMap[event.id],
                        results: values.eventPropertiesCacheMap[event.id].results.map((p) =>
                            p.id === definition.id ? definition : p
                        ),
                    }

                    cache.apiCache = {
                        ...cache.apiCache,
                        [eventCacheKey]: updatedProperties,
                    }

                    return {
                        ...values.eventPropertiesCacheMap,
                        [event.id]: updatedProperties,
                    }
                },
            },
        ],
    })),
    selectors(() => ({
        showVerifiedFilter: [
            (s) => [s.eventDefinitions, s.filters],
            (eventDefinitions: EventDefinitionsPaginatedResponse, filters: Filters): boolean =>
                filters.verified !== undefined ||
                (eventDefinitions.results.length > 0 && 'verified' in eventDefinitions.results[0]),
        ],
        bulkEditLoading: [
            (s) => [s.bulkVerifiedResultLoading, s.bulkHiddenResultLoading],
            (bulkVerifiedResultLoading: boolean, bulkHiddenResultLoading: boolean): boolean =>
                bulkVerifiedResultLoading || bulkHiddenResultLoading,
        ],
        // Convert filters to API params
        paramsFromFilters: [
            (s) => [s.filters],
            (filters: Filters) => {
                const params: Record<string, any> = {
                    search: filters.event,
                    ordering: filters.ordering,
                    event_type: filters.event_type,
                }
                if (filters.tags && filters.tags.length > 0) {
                    params.tags = JSON.stringify(filters.tags)
                }
                if (filters.verified !== undefined) {
                    params.verified = filters.verified
                }
                return params
            },
        ],
    })),
    listeners(({ actions, values, cache }) => ({
        setFilters: async ({ debounce }, breakpoint) => {
            if (debounce) {
                cache.filtersLoadPending = true
                await breakpoint(200)
            }
            cache.filtersLoadPending = false
            actions.loadEventDefinitions()
        },
        bulkUpdateVerifiedSuccess: ({ bulkVerifiedResult, payload }) => {
            if (!bulkVerifiedResult) {
                return
            }
            const { verified, updated, skipped } = bulkVerifiedResult
            actions.applyBulkVerifiedUpdates(updated)
            // Clear the selection only now that the request succeeded, so a failure leaves it
            // intact for the user to retry without re-selecting everything.
            payload?.onSuccess?.()
            toastBulkResult(verified ? 'Verified' : 'Unverified', updated.length, skipped.length)
        },
        bulkUpdateVerifiedFailure: () => {
            lemonToast.error('Failed to update verification status')
        },
        bulkUpdateHiddenSuccess: ({ bulkHiddenResult, payload }) => {
            if (!bulkHiddenResult) {
                return
            }
            const { hidden, updated, skipped } = bulkHiddenResult
            actions.applyBulkHiddenUpdates(updated)
            payload?.onSuccess?.()
            toastBulkResult(hidden ? 'Hid' : 'Unhid', updated.length, skipped.length)
        },
        bulkUpdateHiddenFailure: () => {
            lemonToast.error('Failed to update hidden status')
        },
        loadEventDefinitionsSuccess: () => {
            if (cache.eventsStartTime !== undefined) {
                posthog.capture('event definitions page load succeeded', {
                    load_time: performance.now() - cache.eventsStartTime,
                    num_results: values.eventDefinitions.results.length,
                })
                cache.eventsStartTime = undefined
            }
        },
        loadEventDefinitionsFailure: ({ error }) => {
            if (cache.eventsStartTime !== undefined) {
                posthog.capture('event definitions page load failed', {
                    load_time: performance.now() - cache.eventsStartTime,
                    error: error ?? 'There was an unknown error fetching event definitions.',
                })
                cache.eventsStartTime = undefined
            }
        },
        loadPropertiesForEventSuccess: () => {
            if (cache.propertiesStartTime !== undefined) {
                posthog.capture('event definitions page event nested properties load succeeded', {
                    load_time: performance.now() - cache.propertiesStartTime,
                })
                cache.propertiesStartTime = undefined
            }
        },
        loadPropertiesForEventFailure: ({ error }) => {
            if (cache.propertiesStartTime !== undefined) {
                posthog.capture('event definitions page event nested properties load failed', {
                    load_time: performance.now() - cache.propertiesStartTime,
                    error: error ?? 'There was an unknown error fetching nested property definitions.',
                })
                cache.propertiesStartTime = undefined
            }
        },
    })),
    urlToAction(({ actions, values, cache }) => ({
        '/data-management/events': (_, searchParams) => {
            const filtersFromUrl = filtersFromSearchParams(searchParams)

            if (!objectsEqual(values.filters, filtersFromUrl)) {
                actions.setFilters(filtersFromUrl, false)
            } else if (
                // A debounced filter change already writes this URL, so loading here would skip the debounce
                !cache.filtersLoadPending &&
                !values.eventDefinitions.results.length &&
                !values.eventDefinitionsLoading
            ) {
                actions.loadEventDefinitions()
            }
        },
    })),
    actionToUrl(({ values }) => ({
        setFilters: () => [router.values.location.pathname, values.filters],
    })),
])
