import { deepEqual as equal } from 'fast-equals'
import {
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { lazyLoaders, loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'
import { z } from 'zod'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/constants'
import { isActionFilter, isEventFilter, isEventPropertyFilter } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { isString } from 'lib/utils/guards'
import { localStorageSlot } from 'lib/utils/localStorageSlot'
import { objectClean, objectsEqual } from 'lib/utils/objects'
import { toParams } from 'lib/utils/url'
import { createPlaylist } from 'scenes/session-recordings/playlist/playlistUtils'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'
import { urls } from 'scenes/urls'

import {
    NodeKind,
    RecordingOrder,
    RecordingsQuery,
    RecordingsQueryResponse,
    VALID_RECORDING_ORDERS,
} from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    FilterType,
    LegacyRecordingFilters,
    LogEntryPropertyFilter,
    MatchedRecordingEvent,
    PropertyFilterType,
    PropertyOperator,
    RecordingDurationFilter,
    RecordingUniversalFilters,
    SavedSessionRecordingPlaylistsResult,
    SessionRecordingId,
    SessionRecordingType,
    UniversalFilterValue,
    UniversalFiltersGroup,
} from '~/types'

import { deletedRecordingsLogic } from '../deletedRecordingsLogic'
import {
    DEFAULT_RECORDING_FILTERS_ORDER_BY,
    convertUniversalFiltersToRecordingsQuery,
    isValidRecordingOrder,
} from '../filters/recordingsQueryConversions'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { filtersFromUniversalFilterGroups, isUniversalFilters } from '../utils'
import { playlistFiltersLogic } from './playlistFiltersLogic'

// Re-exported for back-compat with existing import sites; the implementations now live in the leaf
// `recordingsQueryConversions` module so they can be imported without pulling in this logic file.
export { DEFAULT_RECORDING_FILTERS_ORDER_BY, convertUniversalFiltersToRecordingsQuery }
import type { FeatureFlagsSet } from '../../../lib/logic/featureFlagLogic'
import type { RecordingOrderDirection } from '../../../queries/schema/schema-general'
import type { AutoplayDirection } from '../../../types'
import type { HideViewedRecordingsOptions } from '../player/playerSettingsLogic'
import type { SessionRecordingFilterType } from '../sessionRecordingEventUsageLogic'
import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
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
    matchedEvents: MatchedRecordingEvent[]
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

export const MAX_SELECTED_RECORDINGS = 20
export const DELETE_CONFIRMATION_TEXT = 'delete'

// How long a landed list response answers a repeat of the same request. Two seconds is shorter
// than the gap the duplicates arrive in, and five seconds gives a person clicking around rows
// they would call stale, so three seconds covers the repeats and keeps the rows fresh.
export const LIST_MEMO_WINDOW_MS = 3000

/**
 * The list responses that landed inside `LIST_MEMO_WINDOW_MS`, keyed by team and request.
 *
 * This outlives the logic on purpose. An embedded playlist unmounts with the tab or the page that
 * holds it, so most repeats arrive on a fresh logic instance and a per-instance memo would miss
 * them. The team id is part of the key because the request parameters do not carry it, and a team
 * switch must never answer from another team's rows.
 */
const landedListResponses = new Map<string, { response: RecordingsQueryResponse; completedAt: number }>()

const memoizedListResponse = (memoKey: string): RecordingsQueryResponse | undefined => {
    const landed = landedListResponses.get(memoKey)
    return landed && performance.now() - landed.completedAt < LIST_MEMO_WINDOW_MS ? landed.response : undefined
}

const memoizeListResponse = (memoKey: string, response: RecordingsQueryResponse, completedAt: number): void => {
    // Drop what the window no longer covers, so a long session cannot grow the map.
    for (const [key, landed] of landedListResponses) {
        if (completedAt - landed.completedAt >= LIST_MEMO_WINDOW_MS) {
            landedListResponses.delete(key)
        }
    }
    landedListResponses.set(memoKey, { response, completedAt })
}

/** The memo outlives a kea context, so a test has to start from an empty one. */
export const clearMemoizedListResponses = (): void => landedListResponses.clear()

const getDefaultFilterTestAccounts = (): boolean => {
    const stored = localStorage.getItem('default_filter_test_accounts')
    return stored === 'true'
}

// Keyed per team so a sort preference does not leak across accounts.
export const preferredRecordingsSortStorage = localStorageSlot(
    () => `${getCurrentTeamId()}__replay_list_preferred_sort`,
    z.object({ order: z.enum(VALID_RECORDING_ORDERS), order_direction: z.enum(['ASC', 'DESC']) })
)

export const DEFAULT_RECORDING_FILTERS: RecordingUniversalFilters = {
    filter_test_accounts: false,
    date_from: '-3d',
    date_to: null,
    filter_group: { ...DEFAULT_UNIVERSAL_GROUP_FILTER },
    duration: [defaultRecordingDurationFilter],
    order: DEFAULT_RECORDING_FILTERS_ORDER_BY,
    order_direction: 'DESC',
}

export const getEffectiveRecordingFilters = (
    filters: RecordingUniversalFilters,
    featureFlags: FeatureFlagsSet
): RecordingUniversalFilters =>
    featureFlags[FEATURE_FLAGS.REPLAY_RECOMMENDED_RECORDINGS_FILTER_EXPERIMENT] === 'test'
        ? filters
        : { ...filters, recommended_only: false }

export const getDefaultFilters = (
    personUUID?: PersonUUID,
    pinnedFilters?: UniversalFiltersGroup,
    urlFilters?: Partial<RecordingUniversalFilters>
): RecordingUniversalFilters => {
    const filterTestAccounts = getDefaultFilterTestAccounts()
    const hasSpecificIntent = !!personUUID || !!pinnedFilters || !!urlFilters
    const preferredSort = hasSpecificIntent ? null : preferredRecordingsSortStorage.get()
    const defaults: RecordingUniversalFilters = {
        ...DEFAULT_RECORDING_FILTERS,
        filter_test_accounts: filterTestAccounts,
        date_from: personUUID ? '-30d' : '-3d',
        order: preferredSort?.order ?? DEFAULT_RECORDING_FILTERS.order,
        order_direction: preferredSort?.order_direction ?? DEFAULT_RECORDING_FILTERS.order_direction,
    }
    if (pinnedFilters) {
        defaults.filter_group = mergePinnedFilters(defaults.filter_group, pinnedFilters)
    }
    return defaults
}

function mergePinnedFilters(
    filterGroup: UniversalFiltersGroup,
    pinnedFilters: UniversalFiltersGroup
): UniversalFiltersGroup {
    const pinnedValues = pinnedFilters.values
    if (pinnedValues.length === 0) {
        return filterGroup
    }

    const firstGroup = filterGroup.values[0]
    const isNestedGroup = firstGroup && 'values' in firstGroup && 'type' in firstGroup

    if (isNestedGroup) {
        const nested = firstGroup as UniversalFiltersGroup
        const existingNonPinned = nested.values.filter((v) => !pinnedValues.some((pv) => equal(v, pv)))
        return {
            ...filterGroup,
            values: [{ ...nested, values: [...pinnedValues, ...existingNonPinned] }, ...filterGroup.values.slice(1)],
        }
    }

    const existingNonPinned = filterGroup.values.filter((v) => !pinnedValues.some((pv) => equal(v, pv)))
    return {
        ...filterGroup,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: [...pinnedValues, ...existingNonPinned],
            },
        ],
    }
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

    if ('recommended_only' in filters && typeof filters.recommended_only !== 'boolean') {
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

/**
 * Saved playlists persisted before universal filters store the legacy shape, which has no
 * `filter_group` for the filter UI to render or for the query converter to read. Anything loading
 * stored filters has to come through here, or a legacy playlist silently applies no filters at all.
 */
export function asUniversalFilters(
    filters: RecordingUniversalFilters | LegacyRecordingFilters | undefined | null
): RecordingUniversalFilters | undefined {
    if (!filters) {
        return undefined
    }
    return isUniversalFilters(filters) ? filters : convertLegacyFiltersToUniversalFilters({}, filters)
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
        // `surfacing_score` is ordered server-side and isn't carried on the recording object, so any
        // key not present resolves to undefined here and the pair is treated as incomparable (order preserved).
        const orderA = (a as Record<string, any>)[orderKey]
        const orderB = (b as Record<string, any>)[orderKey]
        const incomparable = orderA === undefined || orderB === undefined
        const left_greater = order_direction === 'DESC' ? -1 : 1
        const right_greater = order_direction === 'DESC' ? 1 : -1
        return incomparable ? 0 : orderA > orderB ? left_greater : right_greater
    })
}

export interface SessionRecordingPlaylistLogicProps {
    logicKey?: string
    /**
     * Which surface embeds this playlist, stamped on `recording list fetched`. Set it wherever the
     * playlist is one part of another page, so its list loads can be told apart from the replay
     * scene's own. Left unset, the event carries no source, as it did before.
     */
    analyticsSource?: string
    personUUID?: PersonUUID
    distinctIds?: string[]
    updateSearchParams?: boolean
    autoPlay?: boolean
    onlyPinned?: boolean
    type?: 'filters' | 'collection'
    filters?: RecordingUniversalFilters
    onFiltersChange?: (filters: RecordingUniversalFilters) => void
    /**
     * Called with each freshly loaded page of recordings (not the accumulated list). `isFirstPage`
     * is false for the pages scrolling adds on either end, so a host page can tell the list it
     * first rendered from the ones paging appended to it.
     */
    onRecordingsLoaded?: (recordings: SessionRecordingType[], isFirstPage: boolean) => void
    /**
     * Called once each time the recording the player shows changes — clicked, played next,
     * picked via the URL, or the implicit autoplay fallback to the top of the list (on first
     * load, and again when a reload changes which recording is at the top). Re-selecting the
     * recording already shown does not re-fire.
     */
    onRecordingSelected?: (recordingId: SessionRecordingType['id']) => void
    pinnedFilters?: UniversalFiltersGroup
    pinnedRecordings?: (SessionRecordingType | string)[]
    onPinnedChange?: (recording: SessionRecordingType, pinned: boolean) => void
}

/**
 * The most recent recordings list request this logic issued. `promise` is dropped once the response
 * lands, so only a live request can be waited on, while `selectedRecordingId` outlives it and
 * records which recording the server was already asked to include. What the request returned goes
 * to `landedListResponses` instead, which outlives the logic.
 */
interface IssuedListRequest {
    key: string
    selectedRecordingId: RecordingsQuery['session_recording_id']
    promise: Promise<RecordingsQueryResponse> | undefined
}

const isRelativeDate = (x: RecordingUniversalFilters['date_from']): boolean => !!x && x.startsWith('-')

/**
 * Filter keys a caller scopes the list with, so they never count as viewer edits. A saved filter set
 * carries `experiment_exposure` through a whole-object dispatch, and marking it would unscope the
 * experiment tab's list. `session_ids` is how that tab's watch cards scope the list, and the viewer
 * can clear them from the list header, so the same holds.
 */
const CALLER_OWNED_FILTER_KEYS: string[] = ['experiment_exposure', 'session_ids']

/** The filters state `setFilters` produces, so a caller can compare before it dispatches. */
const applyFilterUpdate = (
    state: RecordingUniversalFilters,
    update: Partial<RecordingUniversalFilters>,
    pinnedFilters?: UniversalFiltersGroup
): RecordingUniversalFilters => {
    const newState = {
        ...state,
        date_to: update.date_from && isRelativeDate(update.date_from) ? null : state.date_to,
        ...update,
    }
    if (pinnedFilters) {
        newState.filter_group = mergePinnedFilters(newState.filter_group, pinnedFilters)
    }
    return newState
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sessionRecordingsPlaylistLogicValues {
    deletedRecordingIds: Set<string> // deletedRecordingsLogic
    featureFlags: FeatureFlagsSet // featureFlagLogic
    receivedFeatureFlags: boolean // featureFlagLogic
    autoplayDirection: AutoplayDirection // playerSettingsLogic
    hideViewedRecordings: HideViewedRecordingsOptions // playerSettingsLogic
    activeSessionRecording: SessionRecordingType | undefined
    activeSessionRecordingId: SessionRecordingId | undefined
    addToCollectionSearch: string
    allowEventPropertyExpansion: boolean
    allowHogQLFilters: boolean
    collectionsForBulkAdd: SavedSessionRecordingPlaylistsResult
    collectionsForBulkAddLoading: boolean
    deleteConfirmationText: string
    eventsHaveSessionId: Record<string, boolean>
    eventsHaveSessionIdLoading: boolean
    filters: RecordingUniversalFilters
    hasNext: boolean
    hiddenRecordings: SessionRecordingType[]
    hiddenRecordingsCount: number
    isAddToCollectionModalOpen: boolean
    isCreatingNewCollectionInModal: boolean
    isDeleteSelectedRecordingsDialogOpen: boolean
    isDeletingSelectedRecordings: boolean
    isScopedByCaller: boolean
    logicProps: SessionRecordingPlaylistLogicProps
    matchingEventsMatchType: MatchingEventsMatchType
    newCollectionName: string
    nextSessionRecording: Partial<SessionRecordingType> | undefined
    otherRecordings: SessionRecordingType[]
    pinnedFilters: UniversalFiltersGroup | undefined
    pinnedRecordings: SessionRecordingType[]
    pinnedRecordingsLoading: boolean
    recordings: SessionRecordingType[]
    recordingsCount: number
    selectedRecordingId: SessionRecordingType['id'] | null
    selectedRecordingOutsideFilters: boolean
    selectedRecordingsIds: string[]
    sessionRecordings: SessionRecordingType[]
    sessionRecordingsAPIErrored: boolean
    sessionRecordingsResponse: RecordingsQueryResponse & {
        order: RecordingsQuery['order']
        order_direction: RecordingsQuery['order_direction']
    }
    sessionRecordingsResponseLoading: boolean
    showFilters: boolean
    showSettings: boolean
    totalFiltersCount: number
    unusableEventsInFilter: string[]
    viewerFilterKeys: string[]
    visiblePinnedRecordings: SessionRecordingType[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sessionRecordingsPlaylistLogicActions {
    addDeletedRecordings: (ids: string[]) => {
        ids: string[]
    } // deletedRecordingsLogic
    setFeatureFlags: (
        flags: string[],
        variants: Record<string, boolean | string>
    ) => {
        flags: string[]
        variants: Record<string, boolean | string>
    } // featureFlagLogic
    setHideViewedRecordings: (hideViewedRecordings: HideViewedRecordingsOptions) => {
        hideViewedRecordings: HideViewedRecordingsOptions
    } // playerSettingsLogic
    setIsFiltersExpanded: (isFiltersExpanded: boolean) => {
        isFiltersExpanded: boolean
    } // playlistFiltersLogic
    reportRecordingsListFetched: (
        loadTime: number,
        filters: RecordingUniversalFilters,
        defaultDurationFilter: RecordingDurationFilter,
        page: {
            hasNext: boolean
            isFirstPage: boolean
            resultCount: number
        },
        source?: string | undefined
    ) => {
        defaultDurationFilter: RecordingDurationFilter
        filters: RecordingUniversalFilters
        loadTime: number
        page: {
            hasNext: boolean
            isFirstPage: boolean
            resultCount: number
        }
        source: string | undefined
    } // sessionRecordingEventUsageLogic
    reportRecordingsListFilterAdded: (filterType: SessionRecordingFilterType) => {
        filterType: SessionRecordingFilterType
    } // sessionRecordingEventUsageLogic
    maybeLoadPropertiesForSessions: (sessions: SessionRecordingType[]) => {
        sessions: SessionRecordingType[]
    } // sessionRecordingsListPropertiesLogic
    applyPropertyFilter: (
        propertyKey: string,
        propertyValue: string | undefined
    ) => {
        propertyKey: string
        propertyValue: string | undefined
    }
    handleBulkAddToPlaylist: (short_id: string) => {
        short_id: string
    }
    handleBulkDeleteFromPlaylist: (short_id: string) => {
        short_id: string
    }
    handleBulkMarkAsNotViewed: (shortId?: string) => {
        shortId: string | undefined
    }
    handleBulkMarkAsViewed: (shortId?: string) => {
        shortId: string | undefined
    }
    handleCreateNewCollectionBulkAdd: (onSuccess: () => void) => {
        onSuccess: () => void
    }
    handleDeleteSelectedRecordings: (shortId?: string) => {
        shortId: string | undefined
    }
    handleSelectUnselectAll: (
        checked: boolean,
        type: 'collection' | 'filters'
    ) => {
        checked: boolean
        type: 'collection' | 'filters'
    }
    loadAllRecordings: () => {
        value: true
    }
    loadCollectionsForBulkAdd: (_: any) => any
    loadCollectionsForBulkAddFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCollectionsForBulkAddSuccess: (
        collectionsForBulkAdd: SavedSessionRecordingPlaylistsResult,
        payload?: any
    ) => {
        collectionsForBulkAdd: SavedSessionRecordingPlaylistsResult
        payload?: any
    }
    loadEventsHaveSessionId: () => any
    loadEventsHaveSessionIdFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadEventsHaveSessionIdSuccess: (
        eventsHaveSessionId: Record<string, boolean>,
        payload?: any
    ) => {
        eventsHaveSessionId: Record<string, boolean>
        payload?: any
    }
    loadNext: () => {
        value: true
    }
    loadPinnedRecordings: () => {
        value: true
    }
    loadPinnedRecordingsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPinnedRecordingsSuccess: (
        pinnedRecordings: SessionRecordingType[],
        payload?: {
            value: true
        }
    ) => {
        pinnedRecordings: SessionRecordingType[]
        payload?: {
            value: true
        }
    }
    loadPrev: () => {
        value: true
    }
    loadSessionRecordings: (
        direction?: 'newer' | 'older',
        userModifiedFilters?: Record<string, any>,
        forceRefetch?: boolean
    ) => {
        direction: 'newer' | 'older' | undefined
        forceRefetch: boolean | undefined
        userModifiedFilters: Record<string, any> | undefined
    }
    loadSessionRecordingsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSessionRecordingsSuccess: (
        sessionRecordingsResponse: {
            has_next: boolean
            next_cursor: string | undefined
            order:
                | 'active_seconds'
                | 'activity_score'
                | 'click_count'
                | 'console_error_count'
                | 'duration'
                | 'inactive_seconds'
                | 'keypress_count'
                | 'mouse_activity_count'
                | 'recording_duration'
                | 'recording_ttl'
                | 'start_time'
                | 'surfacing_score'
                | undefined
            order_direction: RecordingOrderDirection | undefined
            results: SessionRecordingType[]
        },
        payload?: {
            direction: 'newer' | 'older' | undefined
            forceRefetch: boolean | undefined
            userModifiedFilters: Record<string, any> | undefined
        }
    ) => {
        sessionRecordingsResponse: {
            has_next: boolean
            next_cursor: string | undefined
            order:
                | 'active_seconds'
                | 'activity_score'
                | 'click_count'
                | 'console_error_count'
                | 'duration'
                | 'inactive_seconds'
                | 'keypress_count'
                | 'mouse_activity_count'
                | 'recording_duration'
                | 'recording_ttl'
                | 'start_time'
                | 'surfacing_score'
                | undefined
            order_direction: RecordingOrderDirection | undefined
            results: SessionRecordingType[]
        }
        payload?: {
            direction: 'newer' | 'older' | undefined
            forceRefetch: boolean | undefined
            userModifiedFilters: Record<string, any> | undefined
        }
    }
    maybeLoadSessionRecordings: (direction?: 'newer' | 'older') => {
        direction: 'newer' | 'older' | undefined
    }
    resetFilters: () => {
        value: true
    }
    setAddToCollectionSearch: (addToCollectionSearch: string) => {
        addToCollectionSearch: string
    }
    setDeleteConfirmationText: (deleteConfirmationText: string) => {
        deleteConfirmationText: string
    }
    setFilters: (
        filters: Partial<RecordingUniversalFilters>,
        userModified?: boolean
    ) => {
        filters: Partial<RecordingUniversalFilters>
        userModified: boolean
    }
    setIsAddToCollectionModalOpen: (isAddToCollectionModalOpen: boolean) => {
        isAddToCollectionModalOpen: boolean
    }
    setIsCreatingNewCollectionInModal: (isCreatingNewCollectionInModal: boolean) => {
        isCreatingNewCollectionInModal: boolean
    }
    setIsDeleteSelectedRecordingsDialogOpen: (isDeleteSelectedRecordingsDialogOpen: boolean) => {
        isDeleteSelectedRecordingsDialogOpen: boolean
    }
    setIsDeletingSelectedRecordings: (isDeletingSelectedRecordings: boolean) => {
        isDeletingSelectedRecordings: boolean
    }
    setNewCollectionName: (newCollectionName: string) => {
        newCollectionName: string
    }
    setSelectedRecordingId: (id: SessionRecordingType['id'] | null) => {
        id: string | null
    }
    setSelectedRecordingsIds: (recordingsIds: string[]) => {
        recordingsIds: string[]
    }
    setShowFilters: (showFilters: boolean) => {
        showFilters: boolean
    }
    setShowSettings: (showSettings: boolean) => {
        showSettings: boolean
    }
    togglePropertyFilter: (
        propertyKey: string,
        propertyValue: string | undefined
    ) => {
        propertyKey: string
        propertyValue: string | undefined
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sessionRecordingsPlaylistLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        logicProps: (arg: any) => SessionRecordingPlaylistLogicProps
        allowEventPropertyExpansion: (featureFlags: FeatureFlagsSet) => boolean
        matchingEventsMatchType: (filters: RecordingUniversalFilters) => MatchingEventsMatchType
        activeSessionRecordingId: (
            selectedRecordingId: string | null,
            recordings: SessionRecordingType[],
            arg: any
        ) => SessionRecordingId | undefined
        activeSessionRecording: (
            activeSessionRecordingId: string | undefined,
            recordings: SessionRecordingType[]
        ) => SessionRecordingType | undefined
        selectedRecordingOutsideFilters: (
            selectedRecordingId: string | null,
            recordings: SessionRecordingType[]
        ) => boolean
        nextSessionRecording: (
            activeSessionRecording: SessionRecordingType | undefined,
            recordings: SessionRecordingType[],
            autoplayDirection: AutoplayDirection
        ) => Partial<SessionRecordingType> | undefined
        hasNext: (
            sessionRecordingsResponse: RecordingsQueryResponse & {
                order: RecordingsQuery['order']
                order_direction: RecordingsQuery['order_direction']
            }
        ) => boolean
        pinnedFilters: (arg: any) => UniversalFiltersGroup | undefined
        isScopedByCaller: (arg: any) => boolean
        totalFiltersCount: (filters: RecordingUniversalFilters, arg: any, arg2: any) => number
        hiddenRecordings: (
            sessionRecordings: SessionRecordingType[],
            hideViewedRecordings: HideViewedRecordingsOptions,
            selectedRecordingId: string | null,
            deletedRecordingIds: Set<string>
        ) => SessionRecordingType[]
        otherRecordings: (
            sessionRecordings: SessionRecordingType[],
            hideViewedRecordings: HideViewedRecordingsOptions,
            pinnedRecordings: SessionRecordingType[],
            deletedRecordingIds: Set<string>,
            selectedRecordingId: string | null,
            filters: RecordingUniversalFilters
        ) => SessionRecordingType[]
        visiblePinnedRecordings: (
            pinnedRecordings: SessionRecordingType[],
            deletedRecordingIds: Set<string>
        ) => SessionRecordingType[]
        recordings: (
            visiblePinnedRecordings: SessionRecordingType[],
            otherRecordings: SessionRecordingType[],
            arg: any
        ) => SessionRecordingType[]
        recordingsCount: (recordings: SessionRecordingType[]) => number
        hiddenRecordingsCount: (hiddenRecordings: SessionRecordingType[]) => number
        allowHogQLFilters: (featureFlags: FeatureFlagsSet) => boolean
    }
}

export type sessionRecordingsPlaylistLogicType = MakeLogicType<
    sessionRecordingsPlaylistLogicValues,
    sessionRecordingsPlaylistLogicActions,
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogicMeta
>

export const sessionRecordingsPlaylistLogic = kea<sessionRecordingsPlaylistLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsPlaylistLogic', key]),
    props({} as SessionRecordingPlaylistLogicProps),
    key(
        (props: SessionRecordingPlaylistLogicProps) =>
            `${props.logicKey ?? ''}-${props.personUUID ?? ''}-${props.updateSearchParams ? '-with-search' : ''}`
    ),
    connect(() => ({
        actions: [
            featureFlagLogic,
            ['setFeatureFlags'],
            sessionRecordingEventUsageLogic,
            ['reportRecordingsListFetched', 'reportRecordingsListFilterAdded'],
            sessionRecordingsListPropertiesLogic,
            ['maybeLoadPropertiesForSessions'],
            playerSettingsLogic,
            ['setHideViewedRecordings'],
            playlistFiltersLogic,
            ['setIsFiltersExpanded'],
            deletedRecordingsLogic,
            ['addDeletedRecordings'],
        ],
        values: [
            featureFlagLogic,
            ['featureFlags', 'receivedFeatureFlags'],
            playerSettingsLogic,
            ['autoplayDirection', 'hideViewedRecordings'],
            deletedRecordingsLogic,
            ['deletedRecordingIds'],
        ],
    })),

    actions({
        // `userModified` is false for filters that come from props rather than from the viewer,
        // so the load they trigger reports no filter edit.
        setFilters: (filters: Partial<RecordingUniversalFilters>, userModified: boolean = true) => ({
            filters,
            userModified,
        }),
        setShowFilters: (showFilters: boolean) => ({ showFilters }),
        setShowSettings: (showSettings: boolean) => ({ showSettings }),
        resetFilters: true,
        applyPropertyFilter: (propertyKey: string, propertyValue: string | undefined) => ({
            propertyKey,
            propertyValue,
        }),
        togglePropertyFilter: (propertyKey: string, propertyValue: string | undefined) => ({
            propertyKey,
            propertyValue,
        }),
        setSelectedRecordingId: (id: SessionRecordingType['id'] | null) => ({
            id,
        }),
        loadAllRecordings: true,
        loadPinnedRecordings: true,
        loadSessionRecordings: (
            direction?: 'newer' | 'older',
            userModifiedFilters?: Record<string, any>,
            /** Issue the request even when an identical one is already in flight. */
            forceRefetch?: boolean
        ) => ({
            direction,
            userModifiedFilters,
            forceRefetch,
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
        setIsDeletingSelectedRecordings: (isDeletingSelectedRecordings: boolean) => ({
            isDeletingSelectedRecordings,
        }),
        handleDeleteSelectedRecordings: (shortId?: string) => ({ shortId }),
        setIsAddToCollectionModalOpen: (isAddToCollectionModalOpen: boolean) => ({ isAddToCollectionModalOpen }),
        setAddToCollectionSearch: (addToCollectionSearch: string) => ({ addToCollectionSearch }),
        setIsCreatingNewCollectionInModal: (isCreatingNewCollectionInModal: boolean) => ({
            isCreatingNewCollectionInModal,
        }),
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
            // A caller can recompute the whole object - the experiment tab does on every variant or
            // watch card - so dispatch only the keys whose value moved. The rest would overwrite a
            // viewer's own edit and take back their ownership of a key the caller never changed.
            const changedFilters = Object.fromEntries(
                Object.entries(props.filters).filter(
                    ([filterKey, value]) =>
                        !oldProps.filters ||
                        !objectsEqual(value, oldProps.filters[filterKey as keyof RecordingUniversalFilters])
                )
            ) as Partial<RecordingUniversalFilters>
            if (Object.keys(changedFilters).length) {
                actions.setFilters(changedFilters, false)
            }
        }
    }),

    loaders(({ props, values, actions, cache }) => ({
        eventsHaveSessionId: [
            {} as Record<string, boolean>,
            {
                loadEventsHaveSessionId: async () => {
                    const filters = filtersFromUniversalFilterGroups(values.filters)
                    // "All events" (id == null) matches any event, so it can always filter recordings
                    const events: FilterType['events'] = filters
                        .filter(isEventFilter)
                        .filter((event) => event.id != null)

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
                next_cursor: undefined,
                order: DEFAULT_RECORDING_FILTERS_ORDER_BY,
                order_direction: 'DESC',
            } as RecordingsQueryResponse & {
                order: RecordingsQuery['order']
                order_direction: RecordingsQuery['order_direction']
            },
            {
                loadSessionRecordings: async ({ direction, userModifiedFilters, forceRefetch }, breakpoint) => {
                    // Captured before the awaits: `values` reads throw if this logic unmounts
                    // mid-flight, and the fetch report must carry the filters the request was
                    // built from, not whatever they are once the response lands.
                    const filters = getEffectiveRecordingFilters(values.filters, values.featureFlags)
                    const convertedQuery = convertUniversalFiltersToRecordingsQuery(filters)
                    const params: RecordingsQuery & { add_events_to_property_queries?: '1' } = {
                        ...convertedQuery,
                        person_uuid: props.personUUID ?? '',
                        // KLUDGE: some persons have >8MB of distinct_ids,
                        // which wouldn't fit in the URL,
                        // so we limit to 100 distinct_ids for now
                        // if you have so many that it is an issue,
                        // you probably want the person UUID PoE optimisation anyway
                        // TODO: maybe we can slice this instead
                        distinct_ids: (props.distinctIds?.length || 0) < 100 ? props.distinctIds : undefined,
                        // Use the limit from filters if set, otherwise use the default limit
                        limit: convertedQuery.limit ?? RECORDINGS_LIMIT,
                        // If a recording is selected from URL, ensure it's always included in results
                        session_recording_id: values.selectedRecordingId ?? undefined,
                        // Hide viewed recordings is filtered server-side so pagination operates on the
                        // filtered set; the client-side otherRecordings filter remains as a backstop.
                        hide_viewed_recordings: values.hideViewedRecordings || undefined,
                    }

                    if (values.allowEventPropertyExpansion) {
                        params.add_events_to_property_queries = '1'
                    }

                    if (userModifiedFilters) {
                        params.user_modified_filters = userModifiedFilters
                    }

                    if (direction === 'older') {
                        // Use cursor-based pagination for loading older recordings
                        if (values.sessionRecordingsResponse?.next_cursor) {
                            params.after = values.sessionRecordingsResponse.next_cursor
                        } else {
                            // Fallback to offset-based pagination if cursor is not available
                            params.offset = values.sessionRecordings.length
                        }
                    }

                    if (direction === 'newer') {
                        // Reset pagination for loading newer recordings
                        params.offset = 0
                        params.after = undefined
                    }

                    // Each list request is a full ClickHouse read, so two identical ones read the
                    // same rows twice. The debounce below cannot prevent the second: it discards
                    // the earlier *result*, but a request already past it has reached the server,
                    // and cancellation does not reach the query layer. So a repeat waits for a
                    // request this logic still has in flight, or answers from the response
                    // `landedListResponses` holds for a few seconds after it landed.
                    // The comparison ignores `user_modified_filters` because the server only feeds
                    // it to an analytics event, so it does not change which rows are read.
                    const requestKey = JSON.stringify({ ...params, user_modified_filters: undefined })
                    const memoKey = `${getCurrentTeamId()}__${requestKey}`
                    const lastRequest: IssuedListRequest | undefined = cache.listRequest
                    // `forceRefetch` skips both paths, because the caller asks for fresh rows.
                    const memoizedResponse = forceRefetch ? undefined : memoizedListResponse(memoKey)
                    const requestInFlight =
                        !forceRefetch && lastRequest?.key === requestKey ? lastRequest.promise : undefined

                    let response: RecordingsQueryResponse
                    // The first two branches issue no request, so they have no fetch to report.
                    // The call that did issue it reports the one read they all answer from.
                    if (memoizedResponse) {
                        response = memoizedResponse
                    } else if (requestInFlight) {
                        response = await requestInFlight
                    } else {
                        await breakpoint(400) // Debounce for lots of quick filter changes

                        const promise = api.recordings.list(params)
                        const request: IssuedListRequest = {
                            key: requestKey,
                            selectedRecordingId: params.session_recording_id,
                            promise,
                        }
                        cache.listRequest = request

                        const startTime = performance.now()
                        try {
                            response = await promise
                        } catch (e) {
                            // A read that failed says nothing about what the server holds, so drop
                            // the entry and let the next request for these parameters go out.
                            if (cache.listRequest === request) {
                                cache.listRequest = undefined
                            }
                            throw e
                        }
                        // The response is here, so nothing can wait on this request any more. The
                        // entry stays, because it records the recording the server was asked for,
                        // and the rows go to the memo a repeat answers from.
                        const completedAt = performance.now()
                        request.promise = undefined
                        memoizeListResponse(memoKey, response, completedAt)
                        const loadTimeMs = completedAt - startTime

                        actions.reportRecordingsListFetched(
                            loadTimeMs,
                            filters,
                            defaultRecordingDurationFilter,
                            {
                                resultCount: response.results.length,
                                hasNext: response.has_next,
                                isFirstPage: !direction,
                            },
                            props.analyticsSource
                        )
                    }

                    // Must run after the fetch report (superseded and abandoned fetches still
                    // count toward load-time metrics) and before the `values` reads below
                    // (they throw once the logic is unmounted).
                    breakpoint()

                    return {
                        has_next:
                            direction === 'newer'
                                ? (values.sessionRecordingsResponse?.has_next ?? true)
                                : response.has_next,
                        next_cursor: direction === 'newer' ? undefined : response.next_cursor,
                        results: response.results,
                        order: params.order,
                        order_direction: params.order_direction,
                    }
                },
            },
        ],
        collectionsForBulkAdd: [
            { results: [], count: 0 } as SavedSessionRecordingPlaylistsResult,
            {
                loadCollectionsForBulkAdd: async (_, breakpoint) => {
                    const response = await api.recordings.listPlaylists(
                        toParams({
                            limit: 30,
                            order: '-last_modified_at',
                            type: 'collection',
                            // Built-in collections can't be added to, so keep them out of the list.
                            collection_type: 'custom',
                            search: values.addToCollectionSearch || undefined,
                        })
                    )
                    breakpoint()
                    return response
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
            props.filters ?? getDefaultFilters(props.personUUID, props.pinnedFilters),
            { persist: true, prefix: `${getCurrentTeamId()}__${key}` },
            {
                setFilters: (state, { filters }) => {
                    try {
                        if (!isValidRecordingFilters(filters)) {
                            posthog.captureException(new Error('Invalid filters provided'), {
                                filters,
                            })
                            return getDefaultFilters(props.personUUID, props.pinnedFilters)
                        }

                        return applyFilterUpdate(state, filters, props.pinnedFilters)
                    } catch (e) {
                        posthog.captureException(e)
                        return getDefaultFilters(props.personUUID, props.pinnedFilters)
                    }
                },
                resetFilters: () => getDefaultFilters(props.personUUID, props.pinnedFilters),
            },
        ],
        /**
         * The filter keys the viewer set themselves. The filter bar dispatches one narrow partial per
         * control, so the payload keys of a viewer-modified `setFilters` are the provenance. It
         * persists next to `filters` so a caller reapplying its own scope at mount leaves what the
         * viewer chose alone.
         */
        viewerFilterKeys: [
            [] as string[],
            { persist: true, prefix: `${getCurrentTeamId()}__${key}` },
            {
                setFilters: (state, { filters, userModified }) => {
                    const keys = Object.keys(filters)
                    if (!userModified) {
                        // A caller writing a key takes it back, so a filter it now owns reapplies.
                        const kept = state.filter((viewerKey) => !keys.includes(viewerKey))
                        return kept.length === state.length ? state : kept
                    }
                    const added = keys.filter(
                        (viewerKey) => !state.includes(viewerKey) && !CALLER_OWNED_FILTER_KEYS.includes(viewerKey)
                    )
                    return added.length ? [...state, ...added] : state
                },
                resetFilters: () => [],
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
                    // Dedupe against a Set so a merge stays O(n + m) rather than O(n * m).
                    const seenIds = new Set(state.map((r) => r.id))
                    const mergedResults: SessionRecordingType[] = [...state]

                    sessionRecordingsResponse.results.forEach((recording) => {
                        if (!seenIds.has(recording.id)) {
                            seenIds.add(recording.id)
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
                // The filtered/pinned lists reload from scratch on a filter change, so a prior selection
                // can no longer be matched against what's on screen - drop it rather than risk deleting
                // recordings the user can't see.
                setFilters: () => [],
                resetFilters: () => [],
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
        isDeletingSelectedRecordings: [
            false,
            {
                setIsDeletingSelectedRecordings: (_, { isDeletingSelectedRecordings }) => isDeletingSelectedRecordings,
            },
        ],
        isAddToCollectionModalOpen: [
            false,
            {
                setIsAddToCollectionModalOpen: (_, { isAddToCollectionModalOpen }) => isAddToCollectionModalOpen,
            },
        ],
        addToCollectionSearch: [
            '',
            {
                setAddToCollectionSearch: (_, { addToCollectionSearch }) => addToCollectionSearch,
                setIsAddToCollectionModalOpen: () => '',
            },
        ],
        isCreatingNewCollectionInModal: [
            false,
            {
                setIsCreatingNewCollectionInModal: (_, { isCreatingNewCollectionInModal }) =>
                    isCreatingNewCollectionInModal,
                setIsAddToCollectionModalOpen: () => false,
            },
        ],
        newCollectionName: [
            '',
            {
                setNewCollectionName: (_, { newCollectionName }) => newCollectionName,
                setIsAddToCollectionModalOpen: () => '',
                setIsCreatingNewCollectionInModal: (state, { isCreatingNewCollectionInModal }) =>
                    isCreatingNewCollectionInModal ? state : '',
            },
        ],
    })),
    listeners(({ props, actions, values, cache }) => {
        // The player can start showing a recording with no action dispatched: under autoPlay it
        // falls back to the first in the list, and moves when a reload changes which recording
        // is first. So selection is reported from the resulting active id after every action
        // that can move it — deduped, since several of them can land on the same recording.
        const notifyRecordingSelected = (): void => {
            const activeId = values.activeSessionRecordingId
            if (activeId) {
                if (cache.lastReportedSelectedRecordingId !== activeId) {
                    cache.lastReportedSelectedRecordingId = activeId
                    props.onRecordingSelected?.(activeId)
                }
            } else if (!values.sessionRecordingsResponseLoading && !values.pinnedRecordingsLoading) {
                // Settled on the empty state (a reload matched nothing): whatever shows next is
                // shown afresh — even the recording reported last — so drop the dedupe. While a
                // load is in flight the empty is transient (one loader's success can observe the
                // other's reload window), and clearing on it would re-report an unchanged top
                // recording once the reload lands.
                cache.lastReportedSelectedRecordingId = undefined
            }
        }

        // Selection is only ever set by user action, so it can go stale once the underlying
        // list changes shape - keep it intersected with what's actually rendered.
        const pruneSelectedRecordingsIds = (): void => {
            if (values.selectedRecordingsIds.length === 0) {
                return
            }
            const visibleIds = new Set(values.recordings.map((r) => r.id))
            const prunedIds = values.selectedRecordingsIds.filter((id) => visibleIds.has(id))
            if (prunedIds.length !== values.selectedRecordingsIds.length) {
                actions.setSelectedRecordingsIds(prunedIds)
            }
        }

        return {
            setFeatureFlags: () => {
                if (!values.filters.recommended_only) {
                    return
                }
                if (values.featureFlags[FEATURE_FLAGS.REPLAY_RECOMMENDED_RECORDINGS_FILTER_EXPERIMENT] === 'test') {
                    actions.loadSessionRecordings()
                } else {
                    // The flag decides this one, so it is not a viewer edit.
                    actions.setFilters({ recommended_only: false }, false)
                }
            },
            loadAllRecordings: () => {
                // The manual refresh asks for fresh rows, so it re-reads even when an identical
                // request is in flight.
                actions.loadSessionRecordings(undefined, undefined, true)
                actions.loadPinnedRecordings()
            },
            setFilters: ({ filters, userModified }) => {
                actions.loadSessionRecordings(undefined, userModified ? filters : undefined)
                props.onFiltersChange?.(values.filters)
                actions.loadEventsHaveSessionId()
            },

            resetFilters: () => {
                actions.loadSessionRecordings()
                props.onFiltersChange?.(values.filters)
            },

            applyPropertyFilter: ({ propertyKey, propertyValue }) => {
                // Validate property value
                if (propertyValue === undefined || propertyValue === null) {
                    return
                }

                // Determine property filter type
                // For recordings: $browser, $os, $device_type, etc are Event properties
                // $geoip_* and custom properties (no $) are Person properties
                // Everything else with $ is Session property
                const filterType =
                    propertyKey.startsWith('$geoip_') || !propertyKey.startsWith('$')
                        ? PropertyFilterType.Person
                        : ['$browser', '$os', '$device_type', '$initial_device_type', '$os_name'].includes(propertyKey)
                          ? PropertyFilterType.Event
                          : PropertyFilterType.Session

                // Create property filter object
                const filter = {
                    type: filterType,
                    key: propertyKey,
                    value: propertyValue,
                    operator: PropertyOperator.Exact,
                } as AnyPropertyFilter

                // Clone the current filter group structure and add to the first nested group
                const currentGroup = values.filters.filter_group
                const newGroup: UniversalFiltersGroup = {
                    ...currentGroup,
                    values: currentGroup.values.map((nestedGroup, index) => {
                        // Add to the first nested group (index 0)
                        if (index === 0 && 'values' in nestedGroup) {
                            return {
                                ...nestedGroup,
                                values: [...nestedGroup.values, filter],
                            } as UniversalFiltersGroup
                        }
                        return nestedGroup
                    }),
                }

                actions.setFilters({ filter_group: newGroup })

                // Show toast notification with human-readable label and view filters button
                const filterLabel = formatPropertyLabel(filter, {})
                lemonToast.success(`Filter applied: ${filterLabel}`, {
                    toastId: `filter-applied-${propertyKey}`,
                    button: {
                        label: 'View filters',
                        action: () => {
                            actions.setIsFiltersExpanded(true)
                        },
                    },
                })
            },

            togglePropertyFilter: ({ propertyKey, propertyValue }) => {
                // Validate property value
                if (propertyValue === undefined || propertyValue === null) {
                    return
                }

                // Determine property filter type
                const filterType =
                    propertyKey.startsWith('$geoip_') || !propertyKey.startsWith('$')
                        ? PropertyFilterType.Person
                        : ['$browser', '$os', '$device_type', '$initial_device_type', '$os_name'].includes(propertyKey)
                          ? PropertyFilterType.Event
                          : PropertyFilterType.Session

                const currentGroup = values.filters.filter_group
                const firstNestedGroup = currentGroup.values[0]

                if (!firstNestedGroup || !('values' in firstNestedGroup)) {
                    return
                }

                // Check if filter with exact (key, value) exists - if so, remove it
                const exactMatchIndex = firstNestedGroup.values.findIndex((filter) => {
                    if ('key' in filter && 'value' in filter && 'operator' in filter) {
                        return (
                            filter.key === propertyKey &&
                            filter.value === propertyValue &&
                            filter.operator === PropertyOperator.Exact
                        )
                    }
                    return false
                })

                let newGroup: UniversalFiltersGroup
                let actionLabel: string

                if (exactMatchIndex !== -1) {
                    // Remove the exact match
                    newGroup = {
                        ...currentGroup,
                        values: currentGroup.values.map((nestedGroup, index) => {
                            if (index === 0 && 'values' in nestedGroup) {
                                return {
                                    ...nestedGroup,
                                    values: nestedGroup.values.filter((_, i) => i !== exactMatchIndex),
                                } as UniversalFiltersGroup
                            }
                            return nestedGroup
                        }),
                    }
                    actionLabel = 'Filter removed'
                } else {
                    // Check if filter with same key but different value exists
                    const sameKeyIndex = firstNestedGroup.values.findIndex((filter) => {
                        if ('key' in filter && 'operator' in filter) {
                            return filter.key === propertyKey && filter.operator === PropertyOperator.Exact
                        }
                        return false
                    })

                    const newFilter = {
                        type: filterType,
                        key: propertyKey,
                        value: propertyValue,
                        operator: PropertyOperator.Exact,
                    }

                    if (sameKeyIndex !== -1) {
                        // Replace the existing filter with same key
                        newGroup = {
                            ...currentGroup,
                            values: currentGroup.values.map((nestedGroup, index) => {
                                if (index === 0 && 'values' in nestedGroup) {
                                    return {
                                        ...nestedGroup,
                                        values: nestedGroup.values.map((filter, i) =>
                                            i === sameKeyIndex ? newFilter : filter
                                        ),
                                    } as UniversalFiltersGroup
                                }
                                return nestedGroup
                            }),
                        }
                        actionLabel = 'Filter replaced'
                    } else {
                        // Add new filter
                        newGroup = {
                            ...currentGroup,
                            values: currentGroup.values.map((nestedGroup, index) => {
                                if (index === 0 && 'values' in nestedGroup) {
                                    return {
                                        ...nestedGroup,
                                        values: [...nestedGroup.values, newFilter],
                                    } as UniversalFiltersGroup
                                }
                                return nestedGroup
                            }),
                        }
                        actionLabel = 'Filter applied'
                    }
                }

                actions.setFilters({ filter_group: newGroup })

                // Show toast notification
                const filterLabel = formatPropertyLabel(
                    { type: filterType, key: propertyKey, value: propertyValue, operator: PropertyOperator.Exact },
                    {}
                )
                lemonToast.success(`${actionLabel}: ${filterLabel}`, {
                    toastId: `filter-toggled-${propertyKey}`,
                    button: {
                        label: 'View filters',
                        action: () => {
                            actions.setIsFiltersExpanded(true)
                        },
                    },
                })
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

            loadSessionRecordingsSuccess: ({ sessionRecordingsResponse, payload }) => {
                actions.maybeLoadPropertiesForSessions(values.sessionRecordings)
                // A load without a direction replaces the list rather than paging it, the same
                // reading the `sessionRecordings` reducer takes.
                props.onRecordingsLoaded?.(sessionRecordingsResponse.results, !payload?.direction)
                pruneSelectedRecordingsIds()
                notifyRecordingSelected()
            },

            loadPinnedRecordingsSuccess: () => {
                pruneSelectedRecordingsIds()
                // Pinned recordings sort first, so this load can change which recording the
                // autoplay fallback shows, just like a list load.
                notifyRecordingSelected()
            },

            setSelectedRecordingId: () => {
                // Close filters when selecting a recording
                actions.setIsFiltersExpanded(false)

                notifyRecordingSelected()

                const recordingIndex = values.sessionRecordings.findIndex((s) => s.id === values.selectedRecordingId)

                // A recording the list does not hold needs a request carrying session_recording_id,
                // which makes the server include it. Once a request asked for this recording, a
                // second one reads the whole first page again and adds nothing: that request is
                // either still in flight, or it already answered without the recording.
                const lastRequest: IssuedListRequest | undefined = cache.listRequest
                if (
                    recordingIndex === -1 &&
                    values.selectedRecordingId &&
                    lastRequest?.selectedRecordingId !== values.selectedRecordingId
                ) {
                    actions.loadSessionRecordings()
                }

                // If we are at the end of the list then try to load more
                if (recordingIndex === values.sessionRecordings.length - 1) {
                    actions.maybeLoadSessionRecordings('older')
                }

                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.WatchSessionRecording)
            },

            addDeletedRecordings: ({ ids }) => {
                if (values.selectedRecordingId && ids.includes(values.selectedRecordingId)) {
                    actions.setSelectedRecordingId(null)
                }
                pruneSelectedRecordingsIds()
            },

            setHideViewedRecordings: () => {
                // Filtering happens server-side, so toggling the filter changes the result set entirely.
                // Reset and refetch from the first page rather than paginating onto the stale cursor.
                actions.loadSessionRecordings()
            },
            handleBulkAddToPlaylist: async ({ short_id }: { short_id: string }) => {
                const requestedCount = values.selectedRecordingsIds.length
                let addedCount = 0
                await lemonToast.promise(
                    (async () => {
                        const result = await api.recordings
                            .bulkAddRecordingsToPlaylist(short_id, values.selectedRecordingsIds)
                            .catch((e) => {
                                // Report real API or network failures; rethrow so the toast still shows its error state.
                                posthog.captureException(e)
                                throw e
                            })
                        // The endpoint answers 200 even when it saved nothing, so trust added_count.
                        if (result.added_count === 0) {
                            throw new Error('No recordings were added to the collection')
                        }
                        addedCount = result.added_count
                        actions.setSelectedRecordingsIds([])

                        // Reload the playlist to show the new recordings
                        handleLoadCollectionRecordings(short_id)
                    })(),
                    {
                        success: () => `${addedCount} recording${addedCount > 1 ? 's' : ''} added to collection!`,
                        error: 'Failed to add to collection!',
                        pending: `Adding ${requestedCount} recording${
                            requestedCount > 1 ? 's' : ''
                        } to the collection...`,
                    },
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
                            await api.recordings.bulkDeleteRecordingsFromPlaylist(
                                short_id,
                                values.selectedRecordingsIds
                            )
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
                    const recordings = type === 'filters' ? values.otherRecordings : values.visiblePinnedRecordings
                    actions.setSelectedRecordingsIds(recordings.map((s) => s.id))
                } else {
                    actions.setSelectedRecordingsIds([])
                }
            },
            handleDeleteSelectedRecordings: async ({ shortId }: { shortId?: string }) => {
                if (values.isDeletingSelectedRecordings) {
                    return
                }

                const idsToDelete = [...values.selectedRecordingsIds]
                const deleteCount = idsToDelete.length
                actions.setIsDeletingSelectedRecordings(true)

                try {
                    const result = await api.recordings.bulkDeleteRecordings(idsToDelete, values.filters.date_from)
                    const deletedIds = idsToDelete.filter((id) => !(result.failed_ids ?? []).includes(id))
                    actions.addDeletedRecordings(deletedIds)
                    actions.setSelectedRecordingsIds([])
                    actions.setDeleteConfirmationText('')
                    actions.setIsDeleteSelectedRecordingsDialogOpen(false)

                    if (shortId) {
                        handleLoadCollectionRecordings(shortId)
                    }

                    const actualCount = deletedIds.length
                    if (actualCount < deleteCount) {
                        lemonToast.warning(
                            `${actualCount} of ${deleteCount} recording${deleteCount > 1 ? 's' : ''} deleted. ${deleteCount - actualCount} failed.`
                        )
                    } else {
                        lemonToast.success(`${actualCount} recording${actualCount > 1 ? 's' : ''} deleted!`)
                    }
                } catch (e) {
                    lemonToast.error('Failed to delete recordings!')
                    posthog.captureException(e)
                } finally {
                    actions.setIsDeletingSelectedRecordings(false)
                }
            },
            handleCreateNewCollectionBulkAdd: async ({ onSuccess }) => {
                const newPlaylist = await createPlaylist({
                    name: values.newCollectionName,
                    type: 'collection',
                })

                if (newPlaylist) {
                    actions.handleBulkAddToPlaylist(newPlaylist.short_id)
                    actions.setIsAddToCollectionModalOpen(false)
                    onSuccess()
                }
            },
            setIsAddToCollectionModalOpen: ({ isAddToCollectionModalOpen }) => {
                if (isAddToCollectionModalOpen) {
                    actions.loadCollectionsForBulkAdd(null)
                }
            },
            setAddToCollectionSearch: async (_, breakpoint) => {
                await breakpoint(200)
                actions.loadCollectionsForBulkAdd(null)
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
                                // The request parameters do not change here, but the rows the server
                                // returns do, so re-read even when an identical request is in flight.
                                actions.loadSessionRecordings(undefined, undefined, true)
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
                                // The request parameters do not change here, but the rows the server
                                // returns do, so re-read even when an identical request is in flight.
                                actions.loadSessionRecordings(undefined, undefined, true)
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
        }
    }),
    selectors({
        logicProps: [() => [(_, props) => props], (props): SessionRecordingPlaylistLogicProps => props],

        allowEventPropertyExpansion: [
            (s) => [s.featureFlags],
            (featureFlags: import('lib/logic/featureFlagLogic').FeatureFlagsSet): boolean => {
                return !!featureFlags[FEATURE_FLAGS.RECORDINGS_PLAYER_EVENT_PROPERTY_EXPANSION]
            },
        ],

        matchingEventsMatchType: [
            (s) => [s.filters],
            (filters: RecordingUniversalFilters): MatchingEventsMatchType => {
                if (!filters) {
                    return { matchType: 'none' }
                }

                const filterValues = filtersFromUniversalFilterGroups(filters)

                const eventFilters = filterValues.filter(isEventFilter)
                const eventPropertyFilters = filterValues.filter(isEventPropertyFilter)
                const actionFilters = filterValues.filter(isActionFilter)

                const hasEvents = !!eventFilters.length
                const hasEventsProperties = !!eventPropertyFilters.length
                const hasActions = !!actionFilters.length
                const simpleEventsFilters = (eventFilters || [])
                    .filter((e) => !e.properties || !e.properties.length)
                    .map((e) => (e.name ? e.name.toString() : null))
                    .filter(Boolean) as string[]
                const hasSimpleEventsFilters = !!simpleEventsFilters.length

                if (hasActions) {
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
            (
                selectedRecordingId: SessionRecordingType['id'] | null,
                recordings: SessionRecordingType[],
                autoPlay
            ): SessionRecordingId | undefined => {
                return selectedRecordingId ? selectedRecordingId : autoPlay ? recordings[0]?.id : undefined
            },
        ],

        activeSessionRecording: [
            (s) => [s.activeSessionRecordingId, s.recordings],
            (
                activeSessionRecordingId: SessionRecordingId | undefined,
                recordings: SessionRecordingType[]
            ): SessionRecordingType | undefined => {
                return recordings.find((rec) => rec.id === activeSessionRecordingId)
            },
        ],

        selectedRecordingOutsideFilters: [
            (s) => [s.selectedRecordingId, s.recordings],
            (selectedRecordingId: SessionRecordingType['id'] | null, recordings: SessionRecordingType[]): boolean => {
                if (!selectedRecordingId) {
                    return false
                }
                return recordings.find((rec) => rec.id === selectedRecordingId)?.matches_filters === false
            },
        ],

        nextSessionRecording: [
            (s) => [s.activeSessionRecording, s.recordings, s.autoplayDirection],
            (
                activeSessionRecording: SessionRecordingType | undefined,
                recordings: SessionRecordingType[],
                autoplayDirection: import('~/types').AutoplayDirection
            ): Partial<SessionRecordingType> | undefined => {
                if (!activeSessionRecording || !autoplayDirection) {
                    return
                }
                const activeSessionRecordingIndex = recordings.findIndex((x) => x.id === activeSessionRecording.id)
                return autoplayDirection === 'newer'
                    ? recordings[activeSessionRecordingIndex - 1]
                    : recordings[activeSessionRecordingIndex + 1]
            },
        ],

        hasNext: [
            (s) => [s.sessionRecordingsResponse],
            (
                sessionRecordingsResponse: RecordingsQueryResponse & {
                    order: RecordingsQuery['order']
                    order_direction: RecordingsQuery['order_direction']
                }
            ) => sessionRecordingsResponse.has_next,
        ],

        pinnedFilters: [
            () => [(_, props) => props.pinnedFilters],
            (pinnedFilters): UniversalFiltersGroup | undefined => pinnedFilters,
        ],

        // props.filters scopes embedded playlists (experiment tab, group page, notebook node).
        isScopedByCaller: [
            () => [(_, props) => props.filters],
            (filters: RecordingUniversalFilters | undefined): boolean => !!filters,
        ],

        totalFiltersCount: [
            (s) => [s.filters, (_, props) => props.personUUID, (_, props) => props.pinnedFilters],
            (filters: RecordingUniversalFilters, personUUID, pinnedFilters) => {
                const defaultFilters = getDefaultFilters(personUUID, pinnedFilters)
                const groupFilters = filtersFromUniversalFilterGroups(filters)
                const pinnedValues: UniversalFilterValue[] = pinnedFilters?.values ?? []
                const userFilterCount = groupFilters.filter((f) => !pinnedValues.some((pv) => equal(f, pv))).length

                return (
                    userFilterCount +
                    (equal(filters.duration?.[0] ?? defaultFilters.duration[0], defaultFilters.duration[0]) ? 0 : 1) +
                    (filters.date_from === defaultFilters.date_from && filters.date_to === defaultFilters.date_to
                        ? 0
                        : 1) +
                    (filters.session_ids?.length ? 1 : 0)
                )
            },
        ],

        hiddenRecordings: [
            (s) => [s.sessionRecordings, s.hideViewedRecordings, s.selectedRecordingId, s.deletedRecordingIds],
            (
                sessionRecordings: SessionRecordingType[],
                hideViewedRecordings: import('../player/playerSettingsLogic').HideViewedRecordingsOptions,
                selectedRecordingId: SessionRecordingType['id'] | null,
                deletedRecordingIds: Set<string>
            ): SessionRecordingType[] => {
                return sessionRecordings.filter((rec) => {
                    if (deletedRecordingIds.has(rec.id)) {
                        return false
                    }

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
            (s) => [
                s.sessionRecordings,
                s.hideViewedRecordings,
                s.pinnedRecordings,
                s.deletedRecordingIds,
                s.selectedRecordingId,
                s.filters,
            ],
            (
                sessionRecordings: SessionRecordingType[],
                hideViewedRecordings: import('../player/playerSettingsLogic').HideViewedRecordingsOptions,
                pinnedRecordings: SessionRecordingType[],
                deletedRecordingIds: Set<string>,
                selectedRecordingId: SessionRecordingType['id'] | null,
                filters: RecordingUniversalFilters
            ): SessionRecordingType[] => {
                const filteredRecordings = sessionRecordings.filter((rec) => {
                    if (deletedRecordingIds.has(rec.id)) {
                        return false
                    }

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

        // pinnedRecordings is a lazyLoader so we can't add filtering there directly
        visiblePinnedRecordings: [
            (s) => [s.pinnedRecordings, s.deletedRecordingIds],
            (pinnedRecordings: SessionRecordingType[], deletedRecordingIds: Set<string>): SessionRecordingType[] => {
                if (deletedRecordingIds.size === 0) {
                    return pinnedRecordings
                }
                return pinnedRecordings.filter((r) => !deletedRecordingIds.has(r.id))
            },
        ],

        recordings: [
            (s) => [s.visiblePinnedRecordings, s.otherRecordings, (_, props) => props.onlyPinned],
            (
                visiblePinnedRecordings: SessionRecordingType[],
                otherRecordings: SessionRecordingType[],
                onlyPinned
            ): SessionRecordingType[] => {
                return onlyPinned ? [...visiblePinnedRecordings] : [...visiblePinnedRecordings, ...otherRecordings]
            },
        ],

        recordingsCount: [
            (s) => [s.recordings],
            (recordings: SessionRecordingType[]): number => {
                return recordings.length
            },
        ],

        hiddenRecordingsCount: [
            (s) => [s.hiddenRecordings],
            (hiddenRecordings: SessionRecordingType[]): number => {
                return hiddenRecordings?.length ?? 0
            },
        ],

        allowHogQLFilters: [
            (s) => [s.featureFlags],
            (featureFlags: import('lib/logic/featureFlagLogic').FeatureFlagsSet): boolean =>
                !!featureFlags[FEATURE_FLAGS.REPLAY_HOGQL_FILTERS],
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
                // A link carries these, not a control the viewer moved in this list, so they do not
                // become viewer keys. The URL keeps them for as long as it holds them.
                actions.setFilters(
                    {
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
                    },
                    false
                )
                return
            }

            if (isReplayURLSearchParams(params)) {
                const updatedFilters: Partial<RecordingUniversalFilters> = {
                    // layer URL filters onto defaults, not the persisted state, so fields the URL
                    // omits don't inherit stale values
                    ...(params.filters && !equal(params.filters, values.filters)
                        ? {
                              ...getDefaultFilters(props.personUUID, props.pinnedFilters, params.filters),
                              ...params.filters,
                          }
                        : {}),
                    ...(params.order && !equal(params.order, values.filters.order) ? { order: params.order } : {}),
                    ...(params.order_direction && !equal(params.order_direction, values.filters.order_direction)
                        ? { order_direction: params.order_direction }
                        : {}),
                }

                if (Object.keys(updatedFilters).length > 0) {
                    // This payload carries the whole set, most of it from defaults rather than from
                    // the URL, so it claims no viewer keys.
                    actions.setFilters({ ...values.filters, ...updatedFilters }, false)
                }
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    // NOTE: It is important this comes after urlToAction, as it will override the default behavior
    afterMount(({ actions, props, values }) => {
        if (props.onlyPinned) {
            return
        }

        // The filters reducer persists to localStorage and rehydrates without validation, so a stale
        // or malformed entry poisons state and makes every later filter change fall back to defaults.
        // Drop a bad rehydrated value here, reusing the check that already guards the URL and setFilters paths.
        if (!isValidRecordingFilters(values.filters)) {
            actions.resetFilters()
            return
        }

        if (
            values.receivedFeatureFlags &&
            values.filters.recommended_only &&
            values.featureFlags[FEATURE_FLAGS.REPLAY_RECOMMENDED_RECORDINGS_FILTER_EXPERIMENT] !== 'test'
        ) {
            // The flag decides this one, so it is not a viewer edit.
            actions.setFilters({ recommended_only: false }, false)
        }

        // If updateSearchParams is enabled and URL has filters different from current state,
        // skip the initial load here. The urlToAction handler will apply the URL filters and
        // trigger loadSessionRecordings with the correct filters. This prevents a race condition
        // where we load with default filters first, then load again with URL filters.
        if (props.updateSearchParams) {
            const searchParams = router.values.searchParams
            if (
                searchParams?.filters &&
                isValidRecordingFilters(searchParams.filters) &&
                !equal(searchParams.filters, values.filters)
            ) {
                // URL has valid filters different from current state - let urlToAction handle the initial load
                return
            }
        }

        // A caller scopes the list with `props.filters`, pins filters into it with
        // `props.pinnedFilters`, or both. The filters reducer persists, so kea rehydrates the stored
        // value over `props.filters` and the first read would carry a filter set the caller never
        // asked for. Reapply what the caller owns in one dispatch, and let the `setFilters` listener
        // issue the one load. A key the viewer set themselves stays theirs, so a scoped list opens
        // scoped without dropping the range or the property they chose. This sits after the URL
        // branch, so a shared link still wins.
        if (props.filters || props.pinnedFilters) {
            const callerFilters: Partial<RecordingUniversalFilters> = { ...props.filters }
            for (const viewerKey of values.viewerFilterKeys) {
                delete callerFilters[viewerKey as keyof RecordingUniversalFilters]
            }
            if (props.pinnedFilters) {
                // Pinned filters are the caller's either way, so they merge over whichever group
                // survived above.
                callerFilters.filter_group = mergePinnedFilters(
                    callerFilters.filter_group ?? values.filters.filter_group,
                    props.pinnedFilters
                )
            }
            if (!equal(applyFilterUpdate(values.filters, callerFilters, props.pinnedFilters), values.filters)) {
                actions.setFilters(callerFilters, false)
                return
            }
        }

        actions.loadSessionRecordings()
    }),
])
