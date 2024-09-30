import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { isAnyPropertyfilter } from 'lib/components/PropertyFilters/utils'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import {
    isActionFilter,
    isEventFilter,
    isLogEntryPropertyFilter,
    isRecordingPropertyFilter,
} from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectClean } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import posthog from 'posthog-js'

import { NodeKind, RecordingsQuery, RecordingsQueryResponse } from '~/queries/schema'
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
import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
import type { sessionRecordingsPlaylistLogicType } from './sessionRecordingsPlaylistLogicType'

export type PersonUUID = string

interface Params {
    filters?: RecordingUniversalFilters
    simpleFilters?: LegacyRecordingFilters
    advancedFilters?: LegacyRecordingFilters
    sessionRecordingId?: SessionRecordingId
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
export type SimpleFiltersType = Pick<LegacyRecordingFilters, 'events' | 'properties'>

export const RECORDINGS_LIMIT = 20
export const PINNED_RECORDINGS_LIMIT = 100 // NOTE: This is high but avoids the need for pagination for now...

export const defaultRecordingDurationFilter: RecordingDurationFilter = {
    type: PropertyFilterType.Recording,
    key: 'duration',
    value: 1,
    operator: PropertyOperator.GreaterThan,
}

export const DEFAULT_RECORDING_FILTERS: RecordingUniversalFilters = {
    filter_test_accounts: false,
    date_from: '-3d',
    date_to: null,
    filter_group: { ...DEFAULT_UNIVERSAL_GROUP_FILTER },
    duration: [defaultRecordingDurationFilter],
}

const DEFAULT_PERSON_RECORDING_FILTERS: RecordingUniversalFilters = {
    ...DEFAULT_RECORDING_FILTERS,
    date_from: '-30d',
}

export const getDefaultFilters = (personUUID?: PersonUUID): RecordingUniversalFilters => {
    return personUUID ? DEFAULT_PERSON_RECORDING_FILTERS : DEFAULT_RECORDING_FILTERS
}

const capturePartialFilters = (filters: Partial<RecordingUniversalFilters>): void => {
    // capture only the partial filters applied (not the full filters object)
    // take each key from the filter and change it to `partial_filter_chosen_${key}`
    const partialFilters = Object.keys(filters).reduce((acc, key) => {
        acc[`partial_filter_chosen_${key}`] = filters[key]
        return acc
    }, {})

    posthog.capture('recording list filters changed', {
        ...partialFilters,
    })
}

export function convertUniversalFiltersToRecordingsQuery(universalFilters: RecordingUniversalFilters): RecordingsQuery {
    const filters = filtersFromUniversalFilterGroups(universalFilters)

    const events: RecordingsQuery['events'] = []
    const actions: RecordingsQuery['actions'] = []
    const properties: RecordingsQuery['properties'] = []
    const console_log_filters: RecordingsQuery['console_log_filters'] = []
    const having_predicates: RecordingsQuery['having_predicates'] = []

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
        order: 'start_time',
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
            ? [{ ...filters.session_recording_duration, key: filters.duration_type_filter || 'duration' }]
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

function sortRecordings(recordings: SessionRecordingType[], order: RecordingsQuery['order']): SessionRecordingType[] {
    const orderKey:
        | 'recording_duration'
        | 'active_seconds'
        | 'inactive_seconds'
        | 'console_error_count'
        | 'click_count'
        | 'keypress_count'
        | 'mouse_activity_count'
        | 'start_time' = order === 'duration' ? 'recording_duration' : order

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
    updateSearchParams?: boolean
    autoPlay?: boolean
    filters?: RecordingUniversalFilters
    onFiltersChange?: (filters: RecordingUniversalFilters) => void
    pinnedRecordings?: (SessionRecordingType | string)[]
    onPinnedChange?: (recording: SessionRecordingType, pinned: boolean) => void
}

export interface SessionSummaryResponse {
    id: SessionRecordingType['id']
    content: string
}

export const sessionRecordingsPlaylistLogic = kea<sessionRecordingsPlaylistLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsPlaylistLogic', key]),
    props({} as SessionRecordingPlaylistLogicProps),
    key(
        (props: SessionRecordingPlaylistLogicProps) =>
            `${props.logicKey}-${props.personUUID}-${props.updateSearchParams ? '-with-search' : ''}`
    ),

    connect({
        actions: [
            eventUsageLogic,
            ['reportRecordingsListFetched', 'reportRecordingsListFilterAdded'],
            sessionRecordingsListPropertiesLogic,
            ['maybeLoadPropertiesForSessions'],
        ],
        values: [
            featureFlagLogic,
            ['featureFlags'],
            playerSettingsLogic,
            ['autoplayDirection', 'hideViewedRecordings'],
        ],
    }),

    actions({
        setFilters: (filters: Partial<RecordingUniversalFilters>) => ({ filters }),
        setShowFilters: (showFilters: boolean) => ({ showFilters }),
        setShowSettings: (showSettings: boolean) => ({ showSettings }),
        setOrderBy: (orderBy: RecordingsQuery['order'] | null) => ({ orderBy }),
        resetFilters: true,
        setSelectedRecordingId: (id: SessionRecordingType['id'] | null) => ({
            id,
        }),
        loadAllRecordings: true,
        loadPinnedRecordings: true,
        loadSessionRecordings: (direction?: 'newer' | 'older') => ({ direction }),
        maybeLoadSessionRecordings: (direction?: 'newer' | 'older') => ({ direction }),
        summarizeSession: (id: SessionRecordingType['id']) => ({ id }),
        loadNext: true,
        loadPrev: true,
        setShowOtherRecordings: (show: boolean) => ({ show }),
    }),
    propsChanged(({ actions, props }, oldProps) => {
        // If the defined list changes, we need to call the loader to either load the new items or change the list
        if (props.pinnedRecordings !== oldProps.pinnedRecordings) {
            actions.loadPinnedRecordings()
        }
        if (props.filters && props.filters !== oldProps.filters) {
            actions.setFilters(props.filters)
        }
    }),

    loaders(({ props, values, actions }) => ({
        sessionSummary: {
            summarizeSession: async ({ id }): Promise<SessionSummaryResponse | null> => {
                if (!id) {
                    return null
                }
                const response = await api.recordings.summarize(id)
                return { content: response.content, id: id }
            },
        },
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
                order: 'start_time',
            } as RecordingsQueryResponse & { order: RecordingsQuery['order'] },
            {
                loadSessionRecordings: async ({ direction }, breakpoint) => {
                    const params: RecordingsQuery = {
                        ...convertUniversalFiltersToRecordingsQuery(values.filters),
                        person_uuid: props.personUUID ?? '',
                        order: values.orderBy,
                        limit: RECORDINGS_LIMIT,
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
                        order: values.orderBy,
                    }
                },
            },
        ],

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
                            order: 'start_time',
                        })

                        recordings = [...recordings, ...fetchedRecordings.results]
                    }
                    // TODO: Check for pinnedRecordings being IDs and fetch them, returning the merged list

                    return recordings
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        selectedOrderBy: [
            null as RecordingsQuery['order'] | null,
            { persist: true, prefix: 'orderByExperiment' },
            {
                setOrderBy: (_, { orderBy }) => orderBy,
            },
        ],
        sessionBeingSummarized: [
            null as null | SessionRecordingType['id'],
            {
                summarizeSession: (_, { id }) => id,
                sessionSummarySuccess: () => null,
            },
        ],
        // If we initialise with pinned recordings then we don't show others by default
        // but if we go down to 0 pinned recordings then we show others
        showOtherRecordings: [
            !props.pinnedRecordings?.length,
            {
                loadPinnedRecordingsSuccess: (state, { pinnedRecordings }) =>
                    pinnedRecordings.length === 0 ? true : state,
                setShowOtherRecordings: (_, { show }) => show,
            },
        ],
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
            {
                setFilters: (state, { filters }) => {
                    return {
                        ...state,
                        ...filters,
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

                summarizeSessionSuccess: (state, { sessionSummary }) => {
                    return sessionSummary
                        ? state.map((s) => {
                              if (s.id === sessionSummary.id) {
                                  return {
                                      ...s,
                                      summary: sessionSummary.content,
                                  }
                              }
                              return s
                          })
                        : state
                },
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
            actions.loadSessionRecordings()
            props.onFiltersChange?.(values.filters)
            capturePartialFilters(filters)
            actions.loadEventsHaveSessionId()
        },

        setOrderBy: () => {
            actions.loadSessionRecordings()
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
            // If we are at the end of the list then try to load more
            const recordingIndex = values.sessionRecordings.findIndex((s) => s.id === values.selectedRecordingId)
            if (recordingIndex === values.sessionRecordings.length - 1) {
                actions.maybeLoadSessionRecordings('older')
            }
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
                const actionFilters = filterValues.filter(isActionFilter)
                const hasVisitedPageFilter = filterValues
                    .filter(isRecordingPropertyFilter)
                    .some((f) => f.key === 'visited_page')

                const hasEvents = !!eventFilters.length
                const hasActions = !!actionFilters.length
                const simpleEventsFilters = (eventFilters || [])
                    .filter((e) => !e.properties || !e.properties.length)
                    .map((e) => (e.name ? e.name.toString() : null))
                    .filter(Boolean) as string[]
                const hasSimpleEventsFilters = !!simpleEventsFilters.length

                if (hasActions || hasVisitedPageFilter) {
                    return { matchType: 'backend', filters }
                }
                if (!hasEvents) {
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

        otherRecordings: [
            (s) => [s.sessionRecordings, s.hideViewedRecordings, s.pinnedRecordings, s.selectedRecordingId, s.orderBy],
            (
                sessionRecordings,
                hideViewedRecordings,
                pinnedRecordings,
                selectedRecordingId,
                orderBy
            ): SessionRecordingType[] => {
                const filteredRecordings = sessionRecordings.filter((rec) => {
                    if (pinnedRecordings.find((pinned) => pinned.id === rec.id)) {
                        return false
                    }

                    if (hideViewedRecordings && rec.viewed && rec.id !== selectedRecordingId) {
                        return false
                    }

                    return true
                })

                return sortRecordings(filteredRecordings, orderBy)
            },
        ],

        recordings: [
            (s) => [s.pinnedRecordings, s.otherRecordings],
            (pinnedRecordings, otherRecordings): SessionRecordingType[] => {
                return [...pinnedRecordings, ...otherRecordings]
            },
        ],

        recordingsCount: [
            (s) => [s.pinnedRecordings, s.otherRecordings, s.showOtherRecordings],
            (pinnedRecordings, otherRecordings, showOtherRecordings): number => {
                return showOtherRecordings ? otherRecordings.length + pinnedRecordings.length : pinnedRecordings.length
            },
        ],
        orderByExperimentFeatureFlag: [
            (s) => [s.featureFlags],
            (featureFlags): RecordingsQuery['order'] | 'control' | null =>
                typeof featureFlags[FEATURE_FLAGS.REPLAY_DEFAULT_SORT_ORDER_EXPERIMENT] === 'string'
                    ? (featureFlags[FEATURE_FLAGS.REPLAY_DEFAULT_SORT_ORDER_EXPERIMENT] as
                          | RecordingsQuery['order']
                          | 'control')
                    : null,
        ],
        orderBy: [
            (s) => [s.selectedOrderBy, s.orderByExperimentFeatureFlag],
            (selectedOrderBy, orderByExperimentFeatureFlag): RecordingsQuery['order'] => {
                if (selectedOrderBy) {
                    return selectedOrderBy
                }

                if (orderByExperimentFeatureFlag === 'control' || !orderByExperimentFeatureFlag) {
                    return 'start_time'
                }

                return orderByExperimentFeatureFlag
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
                filters: values.filters ?? undefined,
                sessionRecordingId: values.selectedRecordingId ?? undefined,
            })

            return [router.values.location.pathname, params, router.values.hashParams, { replace }]
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
        }
        return {
            '*': urlToAction,
        }
    }),

    subscriptions(({ actions }) => ({
        showOtherRecordings: (showOtherRecordings: boolean) => {
            if (showOtherRecordings) {
                actions.loadSessionRecordings()
            }
        },
        orderBy: () => {
            actions.loadSessionRecordings()
        },
    })),

    // NOTE: It is important this comes after urlToAction, as it will override the default behavior
    afterMount(({ actions, values }) => {
        if (values.showOtherRecordings) {
            actions.loadSessionRecordings()
        }
        actions.loadPinnedRecordings()
    }),
])
