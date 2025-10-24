import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { lazyLoaders, loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { isAnyPropertyfilter, isHogQLPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import {
    isActionFilter,
    isEventFilter,
    isEventPropertyFilter,
    isLogEntryPropertyFilter,
    isRecordingPropertyFilter,
} from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isString, objectClean, objectsEqual } from 'lib/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { createPlaylist } from 'scenes/session-recordings/playlist/playlistUtils'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'
import { urls } from 'scenes/urls'

import { ActivationTask, activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { groupsModel } from '~/models/groupsModel'
import {
    NodeKind,
    RecordingOrder,
    RecordingsQuery,
    RecordingsQueryResponse,
    VALID_RECORDING_ORDERS,
} from '~/queries/schema/schema-general'
import {
    EntityTypes,
    FilterLogicalOperator,
    FilterType,
    LegacyRecordingFilters,
    LogEntryPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    RecordingDurationFilter,
    RecordingUniversalFilters,
    SessionRecordingId,
    SessionRecordingType,
    UniversalFilterValue,
} from '~/types'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { filtersFromUniversalFilterGroups } from '../utils'
import { playlistLogic } from './playlistLogic'
import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
import type { sessionRecordingsPlaylistLogicType } from './sessionRecordingsPlaylistLogicType'
import { sessionRecordingsPlaylistSceneLogic } from './sessionRecordingsPlaylistSceneLogic'

export type PersonUUID = string

interface ReplayURLBaseSearchParams {
    sessionRecordingId?: SessionRecordingId
}

/**
 * Allows a caller to send an event property and value that will be converted into the appropriate filters.
 */
type EventPropertyShortcutSearchParams = ReplayURLBaseSearchParams & {
    eventProperty: string
    eventPropertyValue: string
}

/**
 * Allows a caller to send a person property and value that will be converted into the appropriate filters.
 */
type PersonPropertyShortcutSearchParams = ReplayURLBaseSearchParams & {
    personProperty: string
    personPropertyValue: string
}

type ReplayURLSearchParams = ReplayURLBaseSearchParams & {
    filters?: RecordingUniversalFilters
    order?: RecordingsQuery['order']
    order_direction?: RecordingsQuery['order_direction']
}

type ReplayURLSearchParamTypes =
    | ReplayURLSearchParams
    | EventPropertyShortcutSearchParams
    | PersonPropertyShortcutSearchParams

const isEventPropertyShortcutSearchParams = (x: ReplayURLSearchParamTypes): x is EventPropertyShortcutSearchParams => {
    return (x as EventPropertyShortcutSearchParams).eventProperty !== undefined
}

const isPersonPropertyShortcutSearchParams = (
    x: ReplayURLSearchParamTypes
): x is PersonPropertyShortcutSearchParams => {
    return (x as PersonPropertyShortcutSearchParams).personProperty !== undefined
}

function isValidRecordingOrder(order: unknown): boolean {
    return !!order && isString(order) && VALID_RECORDING_ORDERS.includes(order as RecordingOrder)
}

function isValidRecordingOrderDirection(direction: unknown): boolean {
    return !!direction && isString(direction) && ['ASC', 'DESC'].includes(direction)
}

const isReplayURLSearchParams = (x: ReplayURLSearchParamTypes): x is ReplayURLSearchParams => {
    const replayURLSearchParams = x as ReplayURLSearchParams
    return (
        (replayURLSearchParams.filters === undefined || isValidRecordingFilters(replayURLSearchParams.filters)) &&
        (replayURLSearchParams.order === undefined || isValidRecordingOrder(replayURLSearchParams.order)) &&
        (replayURLSearchParams.order_direction === undefined ||
            isValidRecordingOrderDirection(replayURLSearchParams.order_direction))
    )
}

interface NoEventsToMatch {
    matchType: 'none'
}

interface EventNamesMatching {
    matchType: 'name'
    eventNames: string[]
}

interface EventUUIDsMatching {
    matchType: 'uuid'
    eventUUIDs: string[]
}

interface BackendEventsMatching {
    matchType: 'backend'
    filters: RecordingUniversalFilters
}

export type MatchingEventsMatchType = NoEventsToMatch | EventNamesMatching | EventUUIDsMatching | BackendEventsMatching

export const RECORDINGS_LIMIT = 20
export const PINNED_RECORDINGS_LIMIT = 100 // NOTE: This is high but avoids the need for pagination for now...

export const defaultRecordingDurationFilter: RecordingDurationFilter = {
    type: PropertyFilterType.Recording,
    key: 'active_seconds',
    value: 5,
    operator: PropertyOperator.GreaterThan,
}

export const DEFAULT_RECORDING_FILTERS_ORDER_BY = 'start_time'
export const MAX_SELECTED_RECORDINGS = 20
export const DELETE_CONFIRMATION_TEXT = 'delete'

export const DEFAULT_RECORDING_FILTERS: RecordingUniversalFilters = {
    filter_test_accounts: false,
    date_from: '-3d',
    date_to: null,
    filter_group: { ...DEFAULT_UNIVERSAL_GROUP_FILTER },
    duration: [defaultRecordingDurationFilter],
    order: DEFAULT_RECORDING_FILTERS_ORDER_BY,
    order_direction: 'DESC',
}

const DEFAULT_PERSON_RECORDING_FILTERS: RecordingUniversalFilters = {
    ...DEFAULT_RECORDING_FILTERS,
    date_from: '-30d',
}

export const getDefaultFilters = (personUUID?: PersonUUID): RecordingUniversalFilters => {
    return personUUID ? DEFAULT_PERSON_RECORDING_FILTERS : DEFAULT_RECORDING_FILTERS
}

/**
 * Loads the pinned recordings for a given shortId.
 * @param shortId - The shortId of the playlist to load.
 */
const handleLoadCollectionRecordings = (shortId: string): void => {
    let logic = sessionRecordingsPlaylistSceneLogic.findMounted({ shortId: shortId })
    let unmount = null
    if (!logic) {
        logic = sessionRecordingsPlaylistSceneLogic({ shortId: shortId })
        unmount = logic.mount()
    }
    logic.actions.loadPinnedRecordings()
    // Unmount the logic if it was mounted by us
    unmount?.()
}

/**
 * Checks if the filters are valid.
 * @param filters - The filters to check.
 * @returns True if the filters are valid, false otherwise.
 */
export function isValidRecordingFilters(filters: Partial<RecordingUniversalFilters> | undefined): boolean {
    if (!filters || typeof filters !== 'object') {
        return false
    }

    if ('date_from' in filters && filters.date_from !== null && typeof filters.date_from !== 'string') {
        return false
    }
    if ('date_to' in filters && filters.date_to !== null && typeof filters.date_to !== 'string') {
        return false
    }

    if ('filter_test_accounts' in filters && typeof filters.filter_test_accounts !== 'boolean') {
        return false
    }

    if ('duration' in filters) {
        if (!Array.isArray(filters.duration)) {
            return false
        }
        if (
            filters.duration.length > 0 &&
            (!filters.duration[0]?.type || !filters.duration[0]?.key || !filters.duration[0]?.operator)
        ) {
            return false
        }
    }

    if ('filter_group' in filters) {
        const group = filters.filter_group
        if (!group || typeof group !== 'object') {
            return false
        }
        if (!('type' in group) || !('values' in group) || !Array.isArray(group.values)) {
            return false
        }
    }

    if ('order' in filters && typeof filters.order !== 'string') {
        return false
    }

    if (
        'order_direction' in filters &&
        (typeof filters.order_direction !== 'string' || !['ASC', 'DESC'].includes(filters.order_direction ?? 'DESC'))
    ) {
        return false
    }

    return true
}

export function convertUniversalFiltersToRecordingsQuery(universalFilters: RecordingUniversalFilters): RecordingsQuery {
    const filters = filtersFromUniversalFilterGroups(universalFilters)

    const events: RecordingsQuery['events'] = []
    const actions: RecordingsQuery['actions'] = []
    const properties: RecordingsQuery['properties'] = []
    const console_log_filters: RecordingsQuery['console_log_filters'] = []
    const having_predicates: RecordingsQuery['having_predicates'] = []
    let comment_text: RecordingsQuery['comment_text'] = undefined

    // it was possible to store an invalid order key in local storage sometimes, let's just ignore that instead of erroring
    const order: RecordingsQuery['order'] = isValidRecordingOrder(universalFilters.order)
        ? universalFilters.order
        : DEFAULT_RECORDING_FILTERS_ORDER_BY
    const order_direction: RecordingsQuery['order_direction'] = universalFilters.order_direction || 'DESC'

    const durationFilter = universalFilters.duration[0]

    if (durationFilter) {
        having_predicates.push(durationFilter)
    }

    filters.forEach((f) => {
        if (isEventFilter(f)) {
            events.push(f)
        } else if (isActionFilter(f)) {
            actions.push(f)
        } else if (isLogEntryPropertyFilter(f)) {
            console_log_filters.push(f)
        } else if (isHogQLPropertyFilter(f)) {
            properties.push(f)
        } else if (isAnyPropertyfilter(f)) {
            if (isRecordingPropertyFilter(f)) {
                if (f.key === 'visited_page') {
                    events.push({
                        id: '$pageview',
                        name: '$pageview',
                        type: EntityTypes.EVENTS,
                        properties: [
                            {
                                type: PropertyFilterType.Event,
                                key: '$current_url',
                                value: f.value,
                                operator: f.operator,
                            },
                        ],
                    })
                } else if (f.key === 'snapshot_source' && f.value) {
                    having_predicates.push(f)
                } else if (f.key === 'comment_text') {
                    comment_text = f
                }
            } else {
                properties.push(f)
            }
        }
    })

    return {
        kind: NodeKind.RecordingsQuery,
        order: order,
        order_direction: order_direction,
        date_from: universalFilters.date_from,
        date_to: universalFilters.date_to,
        properties,
        events,
        actions,
        console_log_filters,
        having_predicates,
        comment_text,
        filter_test_accounts: universalFilters.filter_test_accounts,
        operand: universalFilters.filter_group.type,
    }
}

export function convertLegacyFiltersToUniversalFilters(
    simpleFilters?: LegacyRecordingFilters,
    advancedFilters?: LegacyRecordingFilters
): RecordingUniversalFilters {
    // we want to remove this, so set a tombstone, lets us see if the dead come back to life
    posthog.capture('legacy_recording_filters_converted_tombstone')

    const filters = combineLegacyRecordingFilters(simpleFilters || {}, advancedFilters || {})

    const events = filters.events ?? []
    const actions = filters.actions ?? []
    const properties = filters.properties ?? []
    const logLevelFilters: LogEntryPropertyFilter[] =
        filters.console_logs && filters.console_logs.length > 0
            ? [
                  {
                      key: 'level',
                      value: filters.console_logs,
                      operator: PropertyOperator.Exact,
                      type: PropertyFilterType.LogEntry,
                  },
              ]
            : []
    const logQueryFilters: LogEntryPropertyFilter[] = filters.console_search_query
        ? [
              {
                  key: 'message',
                  value: [filters.console_search_query],
                  operator: PropertyOperator.Exact,
                  type: PropertyFilterType.LogEntry,
              },
          ]
        : []

    return {
        date_from: filters.date_from || DEFAULT_RECORDING_FILTERS['date_from'],
        date_to: filters.date_to || DEFAULT_RECORDING_FILTERS['date_to'],
        filter_test_accounts:
            filters.filter_test_accounts == undefined
                ? DEFAULT_RECORDING_FILTERS['filter_test_accounts']
                : filters.filter_test_accounts,
        duration: filters.session_recording_duration
            ? [
                  {
                      ...filters.session_recording_duration,
                      key: filters.duration_type_filter || filters.session_recording_duration.key || 'active_seconds',
                  },
              ]
            : DEFAULT_RECORDING_FILTERS['duration'],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [...events, ...actions, ...properties, ...logLevelFilters, ...logQueryFilters],
                },
            ],
        },
        order: DEFAULT_RECORDING_FILTERS.order,
        order_direction: 'DESC',
    }
}

function combineLegacyRecordingFilters(
    simpleFilters: LegacyRecordingFilters,
    advancedFilters: LegacyRecordingFilters
): LegacyRecordingFilters {
    return {
        ...advancedFilters,
        events: [...(simpleFilters?.events || []), ...(advancedFilters?.events || [])],
        properties: [...(simpleFilters?.properties || []), ...(advancedFilters?.properties || [])],
    }
}

// TODO if we're just appending pages... can we avoid this in-memory sorting?
// it's fast to sort an already sorted list but would be nice to avoid it
function sortRecordings(
    recordings: SessionRecordingType[],
    order: RecordingsQuery['order'] | 'duration' = 'start_time',
    order_direction: RecordingsQuery['order_direction']
): SessionRecordingType[] {
    const orderKey: RecordingOrder = order === 'duration' ? 'recording_duration' : order

    return recordings.sort((a, b) => {
        const orderA = a[orderKey]
        const orderB = b[orderKey]
        const incomparable = orderA === undefined || orderB === undefined
        const left_greater = order_direction === 'DESC' ? -1 : 1
        const right_greater = order_direction === 'DESC' ? 1 : -1
        return incomparable ? 0 : orderA > orderB ? left_greater : right_greater
    })
}

export interface SessionRecordingPlaylistLogicProps {
    logicKey?: string
    personUUID?: PersonUUID
    distinctIds?: string[]
    updateSearchParams?: boolean
    autoPlay?: boolean
    filters?: RecordingUniversalFilters
    onFiltersChange?: (filters: RecordingUniversalFilters) => void
    pinnedRecordings?: (SessionRecordingType | string)[]
    onPinnedChange?: (recording: SessionRecordingType, pinned: boolean) => void
}

const isRelativeDate = (x: RecordingUniversalFilters['date_from']): boolean => !!x && x.startsWith('-')

export const sessionRecordingsPlaylistLogic = kea<sessionRecordingsPlaylistLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsPlaylistLogic', key]),
    props({} as SessionRecordingPlaylistLogicProps),
    key(
        (props: SessionRecordingPlaylistLogicProps) =>
            `${props.logicKey}-${props.personUUID}-${props.updateSearchParams ? '-with-search' : ''}`
    ),
    connect(() => ({
        actions: [
            sessionRecordingEventUsageLogic,
            ['reportRecordingsListFetched', 'reportRecordingsListFilterAdded'],
            sessionRecordingsListPropertiesLogic,
            ['maybeLoadPropertiesForSessions'],
            playerSettingsLogic,
            ['setHideViewedRecordings'],
            playlistLogic,
            ['setIsFiltersExpanded'],
        ],
        values: [
            featureFlagLogic,
            ['featureFlags'],
            playerSettingsLogic,
            ['autoplayDirection', 'hideViewedRecordings'],
            groupsModel,
            ['groupsTaxonomicTypes'],
        ],
    })),

    actions({
        setFilters: (filters: Partial<RecordingUniversalFilters>) => ({ filters }),
        setShowFilters: (showFilters: boolean) => ({ showFilters }),
        setShowSettings: (showSettings: boolean) => ({ showSettings }),
        resetFilters: true,
        setSelectedRecordingId: (id: SessionRecordingType['id'] | null) => ({
            id,
        }),
        loadAllRecordings: true,
        loadPinnedRecordings: true,
        loadSessionRecordings: (direction?: 'newer' | 'older', userModifiedFilters?: Record<string, any>) => ({
            direction,
            userModifiedFilters,
        }),
        maybeLoadSessionRecordings: (direction?: 'newer' | 'older') => ({ direction }),
        loadNext: true,
        loadPrev: true,
        setSelectedRecordingsIds: (recordingsIds: string[]) => ({ recordingsIds }),
        handleBulkAddToPlaylist: (short_id: string) => ({ short_id }),
        handleBulkDeleteFromPlaylist: (short_id: string) => ({ short_id }),
        handleSelectUnselectAll: (checked: boolean, type: 'filters' | 'collection') => ({ checked, type }),
        setIsDeleteSelectedRecordingsDialogOpen: (isDeleteSelectedRecordingsDialogOpen: boolean) => ({
            isDeleteSelectedRecordingsDialogOpen,
        }),
        setDeleteConfirmationText: (deleteConfirmationText: string) => ({ deleteConfirmationText }),
        handleDeleteSelectedRecordings: (shortId?: string) => ({ shortId }),
        setIsNewCollectionDialogOpen: (isNewCollectionDialogOpen: boolean) => ({ isNewCollectionDialogOpen }),
        setNewCollectionName: (newCollectionName: string) => ({ newCollectionName }),
        handleCreateNewCollectionBulkAdd: (onSuccess: () => void) => ({ onSuccess }),
        handleBulkMarkAsViewed: (shortId?: string) => ({ shortId }),
        handleBulkMarkAsNotViewed: (shortId?: string) => ({ shortId }),
    }),
    propsChanged(({ actions, props }, oldProps) => {
        // If the defined list changes, we need to call the loader to either load the new items or change the list
        if (!objectsEqual(props.pinnedRecordings, oldProps.pinnedRecordings)) {
            actions.loadPinnedRecordings()
        }
        if (props.filters && !objectsEqual(props.filters, oldProps.filters)) {
            actions.setFilters(props.filters)
        }
    }),

    loaders(({ props, values, actions }) => ({
        eventsHaveSessionId: [
            {} as Record<string, boolean>,
            {
                loadEventsHaveSessionId: async () => {
                    const filters = filtersFromUniversalFilterGroups(values.filters)
                    const events: FilterType['events'] = filters.filter(isEventFilter)

                    if (events === undefined || events.length === 0) {
                        return {}
                    }

                    return await api.propertyDefinitions.seenTogether({
                        eventNames: events.map((event) => event.name),
                        propertyDefinitionName: '$session_id',
                    })
                },
            },
        ],
        sessionRecordingsResponse: [
            {
                results: [],
                has_next: false,
                order: DEFAULT_RECORDING_FILTERS_ORDER_BY,
                order_direction: 'DESC',
            } as RecordingsQueryResponse & {
                order: RecordingsQuery['order']
                order_direction: RecordingsQuery['order_direction']
            },
            {
                loadSessionRecordings: async ({ direction, userModifiedFilters }, breakpoint) => {
                    const params: RecordingsQuery & { add_events_to_property_queries?: '1' } = {
                        ...convertUniversalFiltersToRecordingsQuery(values.filters),
                        person_uuid: props.personUUID ?? '',
                        // KLUDGE: some persons have >8MB of distinct_ids,
                        // which wouldn't fit in the URL,
                        // so we limit to 100 distinct_ids for now
                        // if you have so many that it is an issue,
                        // you probably want the person UUID PoE optimisation anyway
                        // TODO: maybe we can slice this instead
                        distinct_ids: (props.distinctIds?.length || 0) < 100 ? props.distinctIds : undefined,
                        limit: RECORDINGS_LIMIT,
                    }

                    if (values.allowEventPropertyExpansion) {
                        params.add_events_to_property_queries = '1'
                    }

                    if (userModifiedFilters) {
                        params.user_modified_filters = userModifiedFilters
                    }

                    if (direction === 'older') {
                        params.offset = values.sessionRecordings.length
                    }

                    if (direction === 'newer') {
                        params.offset = 0
                    }

                    await breakpoint(400) // Debounce for lots of quick filter changes

                    const startTime = performance.now()
                    const response = await api.recordings.list(params)
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListFetched(loadTimeMs, values.filters, defaultRecordingDurationFilter)

                    breakpoint()

                    return {
                        has_next:
                            direction === 'newer'
                                ? (values.sessionRecordingsResponse?.has_next ?? true)
                                : response.has_next,
                        results: response.results,
                        order: params.order,
                        order_direction: params.order_direction,
                    }
                },
            },
        ],
    })),
    lazyLoaders(({ props }) => ({
        pinnedRecordings: [
            [] as SessionRecordingType[],
            {
                loadPinnedRecordings: async (_, breakpoint) => {
                    await breakpoint(100)

                    // props.pinnedRecordings can be strings or objects.
                    // If objects we can simply use them, if strings we need to fetch them

                    const pinnedRecordings = props.pinnedRecordings ?? []

                    let recordings = pinnedRecordings.filter((x) => typeof x !== 'string') as SessionRecordingType[]
                    const recordingIds = pinnedRecordings.filter((x) => typeof x === 'string') as string[]

                    if (recordingIds.length) {
                        const fetchedRecordings = await api.recordings.list({
                            kind: NodeKind.RecordingsQuery,
                            session_ids: recordingIds,
                            // TODO... wait, do we not support sorting in collections 🤯
                            order: DEFAULT_RECORDING_FILTERS_ORDER_BY,
                            order_direction: 'DESC',
                        })

                        recordings = [...recordings, ...fetchedRecordings.results]
                    }

                    return recordings
                },
            },
        ],
    })),
    reducers(({ props, key }) => ({
        unusableEventsInFilter: [
            [] as string[],
            {
                loadEventsHaveSessionIdSuccess: (_, { eventsHaveSessionId }) => {
                    return Object.entries(eventsHaveSessionId)
                        .filter(([, hasSessionId]) => !hasSessionId)
                        .map(([eventName]) => eventName)
                },
            },
        ],
        filters: [
            props.filters ?? getDefaultFilters(props.personUUID),
            { persist: true, prefix: `${getCurrentTeamId()}__${key}` },
            {
                setFilters: (state, { filters }) => {
                    try {
                        if (!isValidRecordingFilters(filters)) {
                            posthog.captureException(new Error('Invalid filters provided'), {
                                filters,
                            })
                            return getDefaultFilters(props.personUUID)
                        }

                        return {
                            ...state,
                            // if we're setting a relative date_from, then we need to clear the existing date_to
                            date_to: filters.date_from && isRelativeDate(filters.date_from) ? null : state.date_to,
                            ...filters,
                        }
                    } catch (e) {
                        posthog.captureException(e)
                        return getDefaultFilters(props.personUUID)
                    }
                },
                resetFilters: () => getDefaultFilters(props.personUUID),
            },
        ],
        showFilters: [
            true,
            {
                persist: true,
            },
            {
                setShowFilters: (_, { showFilters }) => showFilters,
                setShowSettings: () => false,
            },
        ],
        showSettings: [
            false,
            {
                persist: true,
            },
            {
                setShowSettings: (_, { showSettings }) => showSettings,
                setShowFilters: () => false,
            },
        ],
        sessionRecordings: [
            [] as SessionRecordingType[],
            {
                loadSessionRecordings: (state, { direction }) => {
                    // Reset if we are not paginating
                    return direction ? state : []
                },

                loadSessionRecordingsSuccess: (state, { sessionRecordingsResponse }) => {
                    const mergedResults: SessionRecordingType[] = [...state]

                    sessionRecordingsResponse.results.forEach((recording) => {
                        if (!state.find((r) => r.id === recording.id)) {
                            mergedResults.push(recording)
                        }
                    })

                    return sortRecordings(
                        mergedResults,
                        sessionRecordingsResponse.order,
                        sessionRecordingsResponse.order_direction
                    )
                },

                setSelectedRecordingId: (state, { id }) =>
                    state.map((s) => {
                        if (s.id === id) {
                            return {
                                ...s,
                                viewed: true,
                            }
                        }
                        return { ...s }
                    }),
            },
        ],
        selectedRecordingId: [
            null as SessionRecordingType['id'] | null,
            {
                setSelectedRecordingId: (_, { id }) => id ?? null,
            },
        ],
        sessionRecordingsAPIErrored: [
            false,
            {
                loadSessionRecordingsFailure: () => true,
                loadSessionRecordingSuccess: () => false,
                setFilters: () => false,
                setAdvancedFilters: () => false,
                loadNext: () => false,
                loadPrev: () => false,
            },
        ],
        selectedRecordingsIds: [
            [] as string[],
            {
                setSelectedRecordingsIds: (_, { recordingsIds }) => recordingsIds,
            },
        ],
        isDeleteSelectedRecordingsDialogOpen: [
            false,
            {
                setIsDeleteSelectedRecordingsDialogOpen: (_, { isDeleteSelectedRecordingsDialogOpen }) =>
                    isDeleteSelectedRecordingsDialogOpen,
            },
        ],
        deleteConfirmationText: [
            '',
            {
                setDeleteConfirmationText: (_, { deleteConfirmationText }) => deleteConfirmationText,
            },
        ],
        isNewCollectionDialogOpen: [
            false,
            {
                setIsNewCollectionDialogOpen: (_, { isNewCollectionDialogOpen }) => isNewCollectionDialogOpen,
            },
        ],
        newCollectionName: [
            '',
            {
                setNewCollectionName: (_, { newCollectionName }) => newCollectionName,
            },
        ],
    })),
    listeners(({ props, actions, values }) => ({
        loadAllRecordings: () => {
            actions.loadSessionRecordings()
            actions.loadPinnedRecordings()
        },
        setFilters: ({ filters }) => {
            actions.loadSessionRecordings(undefined, filters)
            props.onFiltersChange?.(values.filters)
            actions.loadEventsHaveSessionId()
        },

        resetFilters: () => {
            actions.loadSessionRecordings()
            props.onFiltersChange?.(values.filters)
        },

        maybeLoadSessionRecordings: ({ direction }) => {
            if (direction === 'older' && !values.hasNext) {
                return // Nothing more to load
            }
            if (values.sessionRecordingsResponseLoading) {
                return // We don't want to load if we are currently loading
            }
            actions.loadSessionRecordings(direction)
        },

        loadSessionRecordingsSuccess: () => {
            actions.maybeLoadPropertiesForSessions(values.sessionRecordings)
        },

        setSelectedRecordingId: () => {
            // Close filters when selecting a recording
            actions.setIsFiltersExpanded(false)

            // If we are at the end of the list then try to load more
            const recordingIndex = values.sessionRecordings.findIndex((s) => s.id === values.selectedRecordingId)
            if (recordingIndex === values.sessionRecordings.length - 1) {
                actions.maybeLoadSessionRecordings('older')
            }

            activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.WatchSessionRecording)
        },

        setHideViewedRecordings: () => {
            actions.maybeLoadSessionRecordings('older')
        },
        handleBulkAddToPlaylist: async ({ short_id }: { short_id: string }) => {
            await lemonToast.promise(
                (async () => {
                    try {
                        await api.recordings.bulkAddRecordingsToPlaylist(short_id, values.selectedRecordingsIds)
                        actions.setSelectedRecordingsIds([])

                        // Reload the playlist to show the new recordings
                        handleLoadCollectionRecordings(short_id)
                    } catch (e) {
                        posthog.captureException(e)
                    }
                })(),
                {
                    success: `${values.selectedRecordingsIds.length} recording${
                        values.selectedRecordingsIds.length > 1 ? 's' : ''
                    } added to collection!`,
                    error: 'Failed to add to collection!',
                    pending: `Adding ${values.selectedRecordingsIds.length} recording${
                        values.selectedRecordingsIds.length > 1 ? 's' : ''
                    } to the collection...`,
                },
                {},
                {
                    button: {
                        label: 'View collection',
                        action: () => router.actions.push(urls.replayPlaylist(short_id)),
                    },
                }
            )
        },
        handleBulkDeleteFromPlaylist: async ({ short_id }: { short_id: string }) => {
            await lemonToast.promise(
                (async () => {
                    try {
                        await api.recordings.bulkDeleteRecordingsFromPlaylist(short_id, values.selectedRecordingsIds)
                        actions.setSelectedRecordingsIds([])

                        // Reload the playlist to see the recordings without the deleted ones
                        handleLoadCollectionRecordings(short_id)
                    } catch (e) {
                        posthog.captureException(e)
                    }
                })(),
                {
                    success: `${values.selectedRecordingsIds.length} recording${
                        values.selectedRecordingsIds.length > 1 ? 's' : ''
                    } removed from collection!`,
                    error: 'Failed to remove from collection!',
                    pending: `Removing ${values.selectedRecordingsIds.length} recording${
                        values.selectedRecordingsIds.length > 1 ? 's' : ''
                    } to the collection...`,
                }
            )
        },
        handleSelectUnselectAll: ({ checked, type }: { checked: boolean; type: 'filters' | 'collection' }) => {
            if (checked) {
                const recordings = type === 'filters' ? values.sessionRecordings : values.pinnedRecordings
                actions.setSelectedRecordingsIds(recordings.map((s) => s.id))
            } else {
                actions.setSelectedRecordingsIds([])
            }
        },
        handleDeleteSelectedRecordings: async ({ shortId }: { shortId?: string }) => {
            await lemonToast.promise(
                (async () => {
                    try {
                        actions.setDeleteConfirmationText('')
                        actions.setIsDeleteSelectedRecordingsDialogOpen(false)
                        await api.recordings.bulkDeleteRecordings(values.selectedRecordingsIds)
                        actions.setSelectedRecordingsIds([])

                        // If it was a collection then we need to reload it, otherwise we need to reload the recordings
                        if (shortId) {
                            handleLoadCollectionRecordings(shortId)
                        } else {
                            actions.loadSessionRecordings()
                        }
                    } catch (e) {
                        posthog.captureException(e)
                    }
                })(),
                {
                    success: `${values.selectedRecordingsIds.length} recording${
                        values.selectedRecordingsIds.length > 1 ? 's' : ''
                    } deleted!`,
                    error: 'Failed to delete recordings!',
                    pending: `Deleting ${values.selectedRecordingsIds.length} recording${
                        values.selectedRecordingsIds.length > 1 ? 's' : ''
                    }...`,
                }
            )
        },
        handleCreateNewCollectionBulkAdd: async ({ onSuccess }) => {
            const newPlaylist = await createPlaylist({
                name: values.newCollectionName,
                type: 'collection',
            })

            if (newPlaylist) {
                actions.handleBulkAddToPlaylist(newPlaylist.short_id)
                actions.setIsNewCollectionDialogOpen(false)
                actions.setNewCollectionName('')
                onSuccess()
            }
        },
        handleBulkMarkAsViewed: async ({ shortId }: { shortId?: string }) => {
            await lemonToast.promise(
                (async () => {
                    try {
                        await api.recordings.bulkViewedRecordings(values.selectedRecordingsIds)
                        actions.setSelectedRecordingsIds([])

                        // If it was a collection then we need to reload it, otherwise we need to reload the recordings
                        if (shortId) {
                            handleLoadCollectionRecordings(shortId)
                        } else {
                            actions.loadSessionRecordings()
                        }
                    } catch (e) {
                        posthog.captureException(e)
                    }
                })(),
                {
                    success: `${values.selectedRecordingsIds.length} recording${
                        values.selectedRecordingsIds.length > 1 ? 's' : ''
                    } marked as viewed!`,
                    error: 'Failed to mark as viewed!',
                    pending: `Marking ${values.selectedRecordingsIds.length} recording${
                        values.selectedRecordingsIds.length > 1 ? 's' : ''
                    }...`,
                }
            )
        },
        handleBulkMarkAsNotViewed: async ({ shortId }: { shortId?: string }) => {
            await lemonToast.promise(
                (async () => {
                    try {
                        await api.recordings.bulkNotViewedRecordings(values.selectedRecordingsIds)
                        actions.setSelectedRecordingsIds([])

                        // If it was a collection then we need to reload it, otherwise we need to reload the recordings
                        if (shortId) {
                            handleLoadCollectionRecordings(shortId)
                        } else {
                            actions.loadSessionRecordings()
                        }
                    } catch (e) {
                        posthog.captureException(e)
                    }
                })(),
                {
                    success: `${values.selectedRecordingsIds.length} recording${
                        values.selectedRecordingsIds.length > 1 ? 's' : ''
                    } marked as not viewed!`,
                    error: 'Failed to mark as not viewed!',
                    pending: `Marking ${values.selectedRecordingsIds.length} recording${
                        values.selectedRecordingsIds.length > 1 ? 's' : ''
                    }...`,
                }
            )
        },
    })),
    selectors({
        logicProps: [() => [(_, props) => props], (props): SessionRecordingPlaylistLogicProps => props],

        allowEventPropertyExpansion: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => {
                return !!featureFlags[FEATURE_FLAGS.RECORDINGS_PLAYER_EVENT_PROPERTY_EXPANSION]
            },
        ],

        matchingEventsMatchType: [
            (s) => [s.filters],
            (filters): MatchingEventsMatchType => {
                if (!filters) {
                    return { matchType: 'none' }
                }

                const filterValues = filtersFromUniversalFilterGroups(filters)

                const eventFilters = filterValues.filter(isEventFilter)
                const eventPropertyFilters = filterValues.filter(isEventPropertyFilter)
                const actionFilters = filterValues.filter(isActionFilter)
                const hasVisitedPageFilter = filterValues
                    .filter(isRecordingPropertyFilter)
                    .some((f) => f.key === 'visited_page')

                const hasEvents = !!eventFilters.length
                const hasEventsProperties = !!eventPropertyFilters.length
                const hasActions = !!actionFilters.length
                const simpleEventsFilters = (eventFilters || [])
                    .filter((e) => !e.properties || !e.properties.length)
                    .map((e) => (e.name ? e.name.toString() : null))
                    .filter(Boolean) as string[]
                const hasSimpleEventsFilters = !!simpleEventsFilters.length

                if (hasActions || hasVisitedPageFilter) {
                    return { matchType: 'backend', filters }
                }

                if (!hasEvents && !hasEventsProperties) {
                    return { matchType: 'none' }
                }

                if (hasEvents && hasSimpleEventsFilters && simpleEventsFilters.length === eventFilters.length) {
                    return {
                        matchType: 'name',
                        eventNames: simpleEventsFilters,
                    }
                }

                return {
                    matchType: 'backend',
                    filters,
                }
            },
        ],

        activeSessionRecordingId: [
            (s) => [s.selectedRecordingId, s.recordings, (_, props) => props.autoPlay],
            (selectedRecordingId, recordings, autoPlay): SessionRecordingId | undefined => {
                return selectedRecordingId ? selectedRecordingId : autoPlay ? recordings[0]?.id : undefined
            },
        ],

        activeSessionRecording: [
            (s) => [s.activeSessionRecordingId, s.recordings],
            (activeSessionRecordingId, recordings): SessionRecordingType | undefined => {
                return recordings.find((rec) => rec.id === activeSessionRecordingId)
            },
        ],

        nextSessionRecording: [
            (s) => [s.activeSessionRecording, s.recordings, s.autoplayDirection],
            (activeSessionRecording, recordings, autoplayDirection): Partial<SessionRecordingType> | undefined => {
                if (!activeSessionRecording || !autoplayDirection) {
                    return
                }
                const activeSessionRecordingIndex = recordings.findIndex((x) => x.id === activeSessionRecording.id)
                return autoplayDirection === 'older'
                    ? recordings[activeSessionRecordingIndex + 1]
                    : recordings[activeSessionRecordingIndex - 1]
            },
        ],

        hasNext: [
            (s) => [s.sessionRecordingsResponse],
            (sessionRecordingsResponse) => sessionRecordingsResponse.has_next,
        ],

        totalFiltersCount: [
            (s) => [s.filters, (_, props) => props.personUUID],
            (filters, personUUID) => {
                const defaultFilters = getDefaultFilters(personUUID)
                const groupFilters = filtersFromUniversalFilterGroups(filters)

                return (
                    groupFilters.length +
                    (equal(filters.duration[0], defaultFilters.duration[0]) ? 0 : 1) +
                    (filters.date_from === defaultFilters.date_from && filters.date_to === defaultFilters.date_to
                        ? 0
                        : 1)
                )
            },
        ],

        hiddenRecordings: [
            (s) => [s.sessionRecordings, s.hideViewedRecordings, s.selectedRecordingId],
            (sessionRecordings, hideViewedRecordings, selectedRecordingId): SessionRecordingType[] => {
                return sessionRecordings.filter((rec) => {
                    if (hideViewedRecordings === 'current-user' && rec.viewed && rec.id !== selectedRecordingId) {
                        return true
                    }

                    if (
                        hideViewedRecordings === 'any-user' &&
                        (rec.viewed || !!rec.viewers.length) &&
                        rec.id !== selectedRecordingId
                    ) {
                        return true
                    }

                    return false
                })
            },
        ],

        otherRecordings: [
            (s) => [s.sessionRecordings, s.hideViewedRecordings, s.pinnedRecordings, s.selectedRecordingId, s.filters],
            (
                sessionRecordings,
                hideViewedRecordings,
                pinnedRecordings,
                selectedRecordingId,
                filters
            ): SessionRecordingType[] => {
                const filteredRecordings = sessionRecordings.filter((rec) => {
                    if (pinnedRecordings.find((pinned) => pinned.id === rec.id)) {
                        return false
                    }

                    if (hideViewedRecordings === 'current-user' && rec.viewed && rec.id !== selectedRecordingId) {
                        return false
                    }

                    if (
                        hideViewedRecordings === 'any-user' &&
                        (rec.viewed || !!rec.viewers.length) &&
                        rec.id !== selectedRecordingId
                    ) {
                        return false
                    }

                    return true
                })

                return sortRecordings(
                    filteredRecordings,
                    filters.order || DEFAULT_RECORDING_FILTERS_ORDER_BY,
                    filters.order_direction || 'DESC'
                )
            },
        ],

        recordings: [
            (s) => [s.pinnedRecordings, s.otherRecordings],
            (pinnedRecordings, otherRecordings): SessionRecordingType[] => {
                return [...pinnedRecordings, ...otherRecordings]
            },
        ],

        recordingsCount: [
            (s) => [s.pinnedRecordings, s.otherRecordings],
            (pinnedRecordings, otherRecordings): number => {
                return otherRecordings.length + pinnedRecordings.length
            },
        ],

        hiddenRecordingsCount: [
            (s) => [s.hiddenRecordings],
            (hiddenRecordings): number => {
                return hiddenRecordings?.length ?? 0
            },
        ],

        allowHogQLFilters: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.REPLAY_HOGQL_FILTERS],
        ],

        allowReplayGroupsFilters: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.REPLAY_GROUPS_FILTERS],
        ],

        taxonomicGroupTypes: [
            (s) => [s.allowHogQLFilters, s.allowReplayGroupsFilters, s.groupsTaxonomicTypes],
            (allowHogQLFilters, allowReplayGroupsFilters, groupsTaxonomicTypes) => {
                const taxonomicGroupTypes = [
                    TaxonomicFilterGroupType.Replay,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.SessionProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                ]

                if (allowHogQLFilters) {
                    taxonomicGroupTypes.push(TaxonomicFilterGroupType.HogQLExpression)
                }

                if (allowReplayGroupsFilters) {
                    taxonomicGroupTypes.push(...groupsTaxonomicTypes)
                }

                return taxonomicGroupTypes
            },
        ],
    }),

    actionToUrl(({ props, values }) => {
        if (!props.updateSearchParams) {
            return {}
        }
        const buildURL = (
            replace: boolean
        ): [
            string,
            ReplayURLSearchParamTypes,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            const params: ReplayURLSearchParamTypes = objectClean({
                ...router.values.searchParams,
                filters: objectsEqual(values.filters, getDefaultFilters(props.personUUID)) ? undefined : values.filters,
                sessionRecordingId: values.selectedRecordingId ?? undefined,
            })

            // we don't keep these if they're still in the URL at this point
            delete (params as any).eventProperty
            delete (params as any).eventPropertyValue
            delete (params as any).personProperty
            delete (params as any).personPropertyValue

            if (!objectsEqual(params, router.values.searchParams)) {
                return [router.values.location.pathname, params, router.values.hashParams, { replace }]
            }
            return [
                router.values.location.pathname,
                router.values.searchParams,
                router.values.hashParams,
                { replace: false },
            ]
        }

        return {
            setSelectedRecordingId: () => buildURL(false),
            setFilters: () => buildURL(true),
            resetFilters: () => buildURL(true),
        }
    }),

    urlToAction(({ actions, values, props }) => {
        const urlToAction = (_: any, params: ReplayURLSearchParamTypes): void => {
            if (!props.updateSearchParams) {
                return
            }

            const nulledSessionRecordingId = params.sessionRecordingId ?? null
            if (nulledSessionRecordingId !== values.selectedRecordingId) {
                actions.setSelectedRecordingId(nulledSessionRecordingId)
            }

            let quickEventFilter: UniversalFilterValue | null = null
            let quickPersonFilter: UniversalFilterValue | null = null
            if (isEventPropertyShortcutSearchParams(params)) {
                quickEventFilter = {
                    type: PropertyFilterType.Event,
                    operator: PropertyOperator.Exact,
                    key: params.eventProperty,
                    value: params.eventPropertyValue,
                }
            }

            if (isPersonPropertyShortcutSearchParams(params)) {
                quickPersonFilter = {
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Exact,
                    key: params.personProperty,
                    value: params.personPropertyValue,
                }
            }

            if (quickEventFilter || quickPersonFilter) {
                actions.setFilters({
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    ...(quickEventFilter ? [quickEventFilter] : []),
                                    ...(quickPersonFilter ? [quickPersonFilter] : []),
                                ],
                            },
                        ],
                    },
                })
                return
            }

            if (isReplayURLSearchParams(params)) {
                const updatedFilters = {
                    ...(params.filters && !equal(params.filters, values.filters) ? params.filters : {}),
                    ...(params.order && !equal(params.order, values.filters.order) ? { order: params.order } : {}),
                    ...(params.order_direction && !equal(params.order_direction, values.filters.order_direction)
                        ? { order_direction: params.order_direction }
                        : {}),
                }

                if (Object.keys(updatedFilters).length > 0) {
                    actions.setFilters({ ...values.filters, ...updatedFilters })
                }
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    // NOTE: It is important this comes after urlToAction, as it will override the default behavior
    afterMount(({ actions }) => {
        actions.loadSessionRecordings()
    }),
])
