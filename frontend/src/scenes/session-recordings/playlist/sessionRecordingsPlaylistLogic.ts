import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { lazyLoaders, loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
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
import { objectClean, objectsEqual } from 'lib/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import posthog from 'posthog-js'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'

import { activationLogic, ActivationTask } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { groupsModel } from '~/models/groupsModel'
import { NodeKind, RecordingOrder, RecordingsQuery, RecordingsQueryResponse } from '~/queries/schema/schema-general'
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
} from '~/types'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { filtersFromUniversalFilterGroups } from '../utils'
import { playlistLogic } from './playlistLogic'
import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
import type { sessionRecordingsPlaylistLogicType } from './sessionRecordingsPlaylistLogicType'
export type PersonUUID = string

interface Params {
    filters?: RecordingUniversalFilters
    simpleFilters?: LegacyRecordingFilters
    advancedFilters?: LegacyRecordingFilters
    sessionRecordingId?: SessionRecordingId
    order?: RecordingsQuery['order']
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

export const DEFAULT_RECORDING_FILTERS: RecordingUniversalFilters = {
    filter_test_accounts: false,
    date_from: '-3d',
    date_to: null,
    filter_group: { ...DEFAULT_UNIVERSAL_GROUP_FILTER },
    duration: [defaultRecordingDurationFilter],
    order: DEFAULT_RECORDING_FILTERS_ORDER_BY,
}

const DEFAULT_PERSON_RECORDING_FILTERS: RecordingUniversalFilters = {
    ...DEFAULT_RECORDING_FILTERS,
    date_from: '-30d',
}

export const getDefaultFilters = (personUUID?: PersonUUID): RecordingUniversalFilters => {
    return personUUID ? DEFAULT_PERSON_RECORDING_FILTERS : DEFAULT_RECORDING_FILTERS
}

/**
 * Checks if the filters are valid.
 * @param filters - The filters to check.
 * @returns True if the filters are valid, false otherwise.
 */
export function isValidRecordingFilters(filters: Partial<RecordingUniversalFilters>): boolean {
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

    return true
}

export function convertUniversalFiltersToRecordingsQuery(universalFilters: RecordingUniversalFilters): RecordingsQuery {
    const filters = filtersFromUniversalFilterGroups(universalFilters)

    const events: RecordingsQuery['events'] = []
    const actions: RecordingsQuery['actions'] = []
    const properties: RecordingsQuery['properties'] = []
    const console_log_filters: RecordingsQuery['console_log_filters'] = []
    const having_predicates: RecordingsQuery['having_predicates'] = []

    const order: RecordingsQuery['order'] = universalFilters.order || DEFAULT_RECORDING_FILTERS_ORDER_BY
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
                }
            } else {
                properties.push(f)
            }
        }
    })

    return {
        kind: NodeKind.RecordingsQuery,
        order: order,
        date_from: universalFilters.date_from,
        date_to: universalFilters.date_to,
        properties,
        events,
        actions,
        console_log_filters,
        having_predicates,
        filter_test_accounts: universalFilters.filter_test_accounts,
        operand: universalFilters.filter_group.type,
    }
}

export function convertLegacyFiltersToUniversalFilters(
    simpleFilters?: LegacyRecordingFilters,
    advancedFilters?: LegacyRecordingFilters
): RecordingUniversalFilters {
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

function sortRecordings(
    recordings: SessionRecordingType[],
    order: RecordingsQuery['order'] | 'duration' = 'start_time'
): SessionRecordingType[] {
    const orderKey: RecordingOrder = order === 'duration' ? 'recording_duration' : order

    return recordings.sort((a, b) => {
        const orderA = a[orderKey]
        const orderB = b[orderKey]
        const incomparible = orderA === undefined || orderB === undefined
        return incomparible ? 0 : orderA > orderB ? -1 : 1
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
            } as RecordingsQueryResponse & { order: RecordingsQuery['order'] },
            {
                loadSessionRecordings: async ({ direction, userModifiedFilters }, breakpoint) => {
                    const params: RecordingsQuery = {
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
                                ? values.sessionRecordingsResponse?.has_next ?? true
                                : response.has_next,
                        results: response.results,
                        order: params.order,
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
                            order: DEFAULT_RECORDING_FILTERS_ORDER_BY,
                        })

                        recordings = [...recordings, ...fetchedRecordings.results]
                    }
                    // TODO: Check for pinnedRecordings being IDs and fetch them, returning the merged list

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

                    return sortRecordings(mergedResults, sessionRecordingsResponse.order)
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
    })),
    selectors({
        logicProps: [() => [(_, props) => props], (props): SessionRecordingPlaylistLogicProps => props],

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

                return sortRecordings(filteredRecordings, filters.order || DEFAULT_RECORDING_FILTERS_ORDER_BY)
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
            Params,
            Record<string, any>,
            {
                replace: boolean
            }
        ] => {
            const params: Params = objectClean({
                ...router.values.searchParams,
                filters: objectsEqual(values.filters, getDefaultFilters(props.personUUID)) ? undefined : values.filters,
                sessionRecordingId: values.selectedRecordingId ?? undefined,
            })

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
        const urlToAction = (_: any, params: Params): void => {
            if (!props.updateSearchParams) {
                return
            }

            const nulledSessionRecordingId = params.sessionRecordingId ?? null
            if (nulledSessionRecordingId !== values.selectedRecordingId) {
                actions.setSelectedRecordingId(nulledSessionRecordingId)
            }

            // Support legacy URLs. Can be removed shortly after release
            if (params.simpleFilters || params.advancedFilters) {
                if (!equal(params.filters, values.filters)) {
                    actions.setFilters(
                        convertLegacyFiltersToUniversalFilters(params.simpleFilters, params.advancedFilters)
                    )
                }
            }

            if (params.filters && !equal(params.filters, values.filters)) {
                actions.setFilters(params.filters)
            }
            if (params.order && !equal(params.order, values.filters.order)) {
                actions.setFilters({ ...values.filters, order: params.order })
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
