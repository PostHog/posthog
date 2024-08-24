import { lemonToast } from '@posthog/lemon-ui'
import { captureException } from '@sentry/react'
import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { isAnyPropertyfilter } from 'lib/components/PropertyFilters/utils'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isActionFilter, isEventFilter, isRecordingPropertyFilter } from 'lib/components/UniversalFilters/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectClean } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import posthog from 'posthog-js'

import {
    AnyPropertyFilter,
    DurationType,
    EntityTypes,
    FilterableLogLevel,
    FilterLogicalOperator,
    FilterType,
    PropertyFilterType,
    PropertyOperator,
    RecordingDurationFilter,
    RecordingFilters,
    RecordingPropertyFilter,
    RecordingUniversalFilters,
    SessionRecordingId,
    SessionRecordingsResponse,
    SessionRecordingType,
} from '~/types'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { filtersFromUniversalFilterGroups } from '../utils'
import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
import type { sessionRecordingsPlaylistLogicType } from './sessionRecordingsPlaylistLogicType'

export type PersonUUID = string
export type SessionOrderingType = DurationType | 'start_time' | 'console_error_count'

interface Params {
    filters?: RecordingUniversalFilters
    simpleFilters?: RecordingFilters
    advancedFilters?: RecordingFilters
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
export type SimpleFiltersType = Pick<RecordingFilters, 'events' | 'properties'>

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

const capturePartialFilters = (filters: Partial<RecordingFilters>): void => {
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

export function convertUniversalFiltersToLegacyFilters(universalFilters: RecordingUniversalFilters): RecordingFilters {
    const filters = filtersFromUniversalFilterGroups(universalFilters)

    const properties: AnyPropertyFilter[] = []
    const events: FilterType['events'] = []
    const actions: FilterType['actions'] = []
    let console_logs: FilterableLogLevel[] = []
    let snapshot_source: AnyPropertyFilter | null = null
    let console_search_query = ''

    filters.forEach((f) => {
        if (isEventFilter(f)) {
            events.push(f)
        } else if (isActionFilter(f)) {
            actions.push(f)
        } else if (isAnyPropertyfilter(f)) {
            if (f.type === PropertyFilterType.Recording) {
                if (f.key === 'console_log_level') {
                    console_logs = f.value as FilterableLogLevel[]
                } else if (f.key === 'console_log_query') {
                    console_search_query = (f.value || '') as string
                } else if (f.key === 'snapshot_source') {
                    const value = f.value as string[] | null
                    if (value) {
                        snapshot_source = f
                    }
                } else if (f.key === 'visited_page') {
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
                }
            } else {
                properties.push(f)
            }
        }
    })

    const durationFilter = universalFilters.duration[0]

    return {
        ...universalFilters,
        properties,
        events,
        actions,
        session_recording_duration: { ...durationFilter, key: 'duration' },
        duration_type_filter: durationFilter.key,
        console_search_query,
        console_logs,
        snapshot_source,
        operand: universalFilters.filter_group.type,
    }
}

export function convertLegacyFiltersToUniversalFilters(
    simpleFilters?: RecordingFilters,
    advancedFilters?: RecordingFilters
): RecordingUniversalFilters {
    const filters = combineRecordingFilters(simpleFilters || {}, advancedFilters || {})

    const events = filters.events ?? []
    const actions = filters.actions ?? []
    const properties = filters.properties ?? []
    const logLevelFilters: RecordingPropertyFilter[] =
        filters.console_logs && filters.console_logs.length > 0
            ? [
                  {
                      key: 'console_log_level',
                      value: filters.console_logs,
                      operator: PropertyOperator.Exact,
                      type: PropertyFilterType.Recording,
                  },
              ]
            : []
    const logQueryFilters: RecordingPropertyFilter[] = filters.console_search_query
        ? [
              {
                  key: 'console_log_query',
                  value: [filters.console_search_query],
                  operator: PropertyOperator.Exact,
                  type: PropertyFilterType.Recording,
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

function combineRecordingFilters(simpleFilters: RecordingFilters, advancedFilters: RecordingFilters): RecordingFilters {
    return {
        ...advancedFilters,
        events: [...(simpleFilters?.events || []), ...(advancedFilters?.events || [])],
        properties: [...(simpleFilters?.properties || []), ...(advancedFilters?.properties || [])],
    }
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
        setOrderBy: (orderBy: SessionOrderingType) => ({ orderBy }),
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
        toggleShowOtherRecordings: (show?: boolean) => ({ show }),
    }),
    propsChanged(({ actions, props }, oldProps) => {
        // If the defined list changes, we need to call the loader to either load the new items or change the list
        if (props.pinnedRecordings !== oldProps.pinnedRecordings) {
            actions.loadPinnedRecordings()
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
                    const events: FilterType['events'] = convertUniversalFiltersToLegacyFilters(values.filters).events

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
            } as SessionRecordingsResponse,
            {
                loadSessionRecordings: async ({ direction }, breakpoint) => {
                    const params = {
                        // TODO: requires a backend change so will include in a separate PR
                        ...convertUniversalFiltersToLegacyFilters(values.filters),
                        person_uuid: props.personUUID ?? '',
                        target_entity_order: values.orderBy,
                        limit: RECORDINGS_LIMIT,
                    }

                    if (values.orderBy === 'start_time') {
                        if (direction === 'older') {
                            params['date_to'] =
                                values.sessionRecordings[values.sessionRecordings.length - 1]?.start_time
                        }

                        if (direction === 'newer') {
                            params['date_from'] = values.sessionRecordings[0]?.start_time
                        }
                    } else {
                        if (direction === 'older') {
                            params['offset'] = values.sessionRecordings.length
                        }

                        if (direction === 'newer') {
                            params['offset'] = 0
                        }
                    }

                    await breakpoint(400) // Debounce for lots of quick filter changes

                    const startTime = performance.now()
                    let response

                    try {
                        response = await api.recordings.list(params)
                    } catch (error: any) {
                        captureException(error)
                        actions.loadSessionRecordingsFailure(error.message, error)

                        return {
                            has_next: false,
                            results: [],
                        }
                    }

                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListFetched(loadTimeMs, values.filters, defaultRecordingDurationFilter)

                    breakpoint()

                    return {
                        has_next:
                            direction === 'newer'
                                ? values.sessionRecordingsResponse?.has_next ?? true
                                : response.has_next,
                        results: response.results,
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
                            session_ids: recordingIds,
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
        orderBy: [
            'start_time' as SessionOrderingType,
            { persist: true },
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
                toggleShowOtherRecordings: (state, { show }) => (show === undefined ? !state : show),
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

                    mergedResults.sort((a, b) => (a.start_time > b.start_time ? -1 : 1))

                    return mergedResults
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

        loadSessionRecordingsFailure: ({ error, errorObject }) => {
            if (errorObject?.data?.type === 'validation_error' && errorObject?.data?.code === 'type_mismatch') {
                lemonToast.error(
                    'One or more property values in your filters are in an incorrect format.' +
                        ' Please check and adjust them to match the required data types.'
                )
            } else {
                lemonToast.error(`Error loading session recordings: ${error}`)
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
                return sessionRecordings
                    .filter((rec) => {
                        if (pinnedRecordings.find((pinned) => pinned.id === rec.id)) {
                            return false
                        }

                        if (hideViewedRecordings && rec.viewed && rec.id !== selectedRecordingId) {
                            return false
                        }

                        return true
                    })
                    .sort((a, b) => (a[orderBy] > b[orderBy] ? -1 : 1))
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
    })),

    // NOTE: It is important this comes after urlToAction, as it will override the default behavior
    afterMount(({ actions, values }) => {
        if (values.showOtherRecordings) {
            actions.loadSessionRecordings()
        }
        actions.loadPinnedRecordings()
    }),
])
