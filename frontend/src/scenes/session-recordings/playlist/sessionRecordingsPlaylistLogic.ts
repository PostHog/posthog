import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectClean, objectsEqual } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import posthog from 'posthog-js'

import {
    AnyPropertyFilter,
    DurationType,
    PropertyFilterType,
    PropertyOperator,
    RecordingDurationFilter,
    RecordingFilters,
    SessionRecordingId,
    SessionRecordingsResponse,
    SessionRecordingType,
} from '~/types'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
import type { sessionRecordingsPlaylistLogicType } from './sessionRecordingsPlaylistLogicType'

export type PersonUUID = string
export type SessionOrderingType = DurationType | 'start_time' | 'console_error_count'

interface Params {
    filters?: RecordingFilters
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
    filters: RecordingFilters
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

export const DEFAULT_SIMPLE_RECORDING_FILTERS: SimpleFiltersType = {
    events: [],
    properties: [],
}

export const DEFAULT_RECORDING_FILTERS: RecordingFilters = {
    session_recording_duration: defaultRecordingDurationFilter,
    properties: [],
    events: [],
    actions: [],
    date_from: '-7d',
    date_to: null,
    console_logs: [],
    console_search_query: '',
}

const DEFAULT_PERSON_RECORDING_FILTERS: RecordingFilters = {
    ...DEFAULT_RECORDING_FILTERS,
    date_from: '-30d',
}

export const getDefaultFilters = (personUUID?: PersonUUID): RecordingFilters => {
    return personUUID ? DEFAULT_PERSON_RECORDING_FILTERS : DEFAULT_RECORDING_FILTERS
}

export const defaultPageviewPropertyEntityFilter = (
    filters: RecordingFilters,
    property: string,
    value?: string
): Partial<RecordingFilters> => {
    const existingPageview = filters.events?.find(({ name }) => name === '$pageview')
    const eventEntityFilters = filters.events ?? []
    const propToAdd = value
        ? {
              key: property,
              value: [value],
              operator: PropertyOperator.Exact,
              type: 'event',
          }
        : {
              key: property,
              value: PropertyOperator.IsNotSet,
              operator: PropertyOperator.IsNotSet,
              type: 'event',
          }

    // If pageview exists, add property to the first pageview event
    if (existingPageview) {
        return {
            events: eventEntityFilters.map((eventFilter) =>
                eventFilter.order === existingPageview.order
                    ? {
                          ...eventFilter,
                          properties: [
                              ...(eventFilter.properties?.filter(({ key }: AnyPropertyFilter) => key !== property) ??
                                  []),
                              propToAdd,
                          ],
                      }
                    : eventFilter
            ),
        }
    } else {
        return {
            events: [
                ...eventEntityFilters,
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    order: eventEntityFilters.length,
                    properties: [propToAdd],
                },
            ],
        }
    }
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

export interface SessionRecordingPlaylistLogicProps {
    logicKey?: string
    personUUID?: PersonUUID
    updateSearchParams?: boolean
    autoPlay?: boolean
    hideSimpleFilters?: boolean
    advancedFilters?: RecordingFilters
    simpleFilters?: RecordingFilters
    onFiltersChange?: (filters: RecordingFilters) => void
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
        setAdvancedFilters: (filters: Partial<RecordingFilters>) => ({ filters }),
        setSimpleFilters: (filters: SimpleFiltersType) => ({ filters }),
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
        if (!objectsEqual(props.advancedFilters, oldProps.advancedFilters)) {
            actions.setAdvancedFilters(props.advancedFilters || {})
        }
        if (!objectsEqual(props.simpleFilters, oldProps.simpleFilters)) {
            actions.setSimpleFilters(props.simpleFilters || {})
        }

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
                    const events = values.filters.events
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
                        ...values.filters,
                        person_uuid: props.personUUID ?? '',
                        target_entity_order: values.orderBy,
                        limit: RECORDINGS_LIMIT,
                    }

                    if (direction === 'older') {
                        params['date_to'] = values.sessionRecordings[values.sessionRecordings.length - 1]?.start_time
                    }

                    if (direction === 'newer') {
                        params['date_from'] = values.sessionRecordings[0]?.start_time
                    }

                    await breakpoint(400) // Debounce for lots of quick filter changes

                    const startTime = performance.now()
                    const response = await api.recordings.list(params)
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListFetched(loadTimeMs)

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
                    // TODO: Check for pinnedRecordings being IDs and fetch them, returnig the merged list

                    return recordings
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        orderBy: [
            'start_time' as SessionOrderingType,
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
        simpleFilters: [
            props.simpleFilters ?? DEFAULT_SIMPLE_RECORDING_FILTERS,
            {
                setSimpleFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                resetFilters: () => DEFAULT_SIMPLE_RECORDING_FILTERS,
            },
        ],
        advancedFilters: [
            props.advancedFilters ?? getDefaultFilters(props.personUUID),
            {
                setAdvancedFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
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
                        } else {
                            return { ...s }
                        }
                    }),

                summarizeSessionSuccess: (state, { sessionSummary }) => {
                    return sessionSummary
                        ? state.map((s) => {
                              if (s.id === sessionSummary.id) {
                                  return {
                                      ...s,
                                      summary: sessionSummary.content,
                                  }
                              } else {
                                  return s
                              }
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
                setAdvancedFilters: () => false,
                setSimpleFilters: () => false,
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
        setSimpleFilters: ({ filters }) => {
            actions.loadSessionRecordings()
            props.onFiltersChange?.(values.filters)
            capturePartialFilters(filters)
            actions.loadEventsHaveSessionId()
        },
        setAdvancedFilters: ({ filters }) => {
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

        filters: [
            (s) => [s.simpleFilters, s.advancedFilters],
            (simpleFilters, advancedFilters): RecordingFilters => {
                return {
                    ...advancedFilters,
                    events: [...(simpleFilters?.events || []), ...(advancedFilters?.events || [])],
                    properties: [...(simpleFilters?.properties || []), ...(advancedFilters?.properties || [])],
                }
            },
        ],

        matchingEventsMatchType: [
            (s) => [s.filters],
            (filters: RecordingFilters | undefined): MatchingEventsMatchType => {
                if (!filters) {
                    return { matchType: 'none' }
                }

                const hasActions = !!filters.actions?.length
                const hasEvents = !!filters.events?.length
                const simpleEventsFilters = (filters.events || [])
                    .filter((e) => !e.properties || !e.properties.length)
                    .map((e) => e.name.toString())
                const hasSimpleEventsFilters = !!simpleEventsFilters.length

                if (hasActions) {
                    return { matchType: 'backend', filters }
                } else {
                    if (!hasEvents) {
                        return { matchType: 'none' }
                    }

                    if (hasEvents && hasSimpleEventsFilters && simpleEventsFilters.length === filters.events?.length) {
                        return {
                            matchType: 'name',
                            eventNames: simpleEventsFilters,
                        }
                    } else {
                        return {
                            matchType: 'backend',
                            filters,
                        }
                    }
                }
            },
        ],

        activeSessionRecordingId: [
            (s) => [s.selectedRecordingId, s.recordings, (_, props) => props.autoPlay],
            (selectedRecordingId, recordings, autoPlay): SessionRecordingId | undefined => {
                return selectedRecordingId
                    ? recordings.find((rec) => rec.id === selectedRecordingId)?.id || selectedRecordingId
                    : autoPlay
                    ? recordings[0]?.id
                    : undefined
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

                return (
                    (filters?.actions?.length || 0) +
                    (filters?.events?.length || 0) +
                    (filters?.properties?.length || 0) +
                    (equal(filters.session_recording_duration, defaultFilters.session_recording_duration) ? 0 : 1) +
                    (filters.date_from === defaultFilters.date_from && filters.date_to === defaultFilters.date_to
                        ? 0
                        : 1) +
                    (filters.console_logs?.length || 0) +
                    (filters.console_search_query?.length ? 1 : 0)
                )
            },
        ],

        otherRecordings: [
            (s) => [s.sessionRecordings, s.hideViewedRecordings, s.pinnedRecordings, s.selectedRecordingId],
            (
                sessionRecordings,
                hideViewedRecordings,
                pinnedRecordings,
                selectedRecordingId
            ): SessionRecordingType[] => {
                return sessionRecordings.filter((rec) => {
                    if (pinnedRecordings.find((pinned) => pinned.id === rec.id)) {
                        return false
                    }

                    if (hideViewedRecordings && rec.viewed && rec.id !== selectedRecordingId) {
                        return false
                    }

                    return true
                })
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
                simpleFilters: values.simpleFilters ?? undefined,
                advancedFilters: values.advancedFilters ?? undefined,
                sessionRecordingId: values.selectedRecordingId ?? undefined,
            })

            return [router.values.location.pathname, params, router.values.hashParams, { replace }]
        }

        return {
            setSelectedRecordingId: () => buildURL(false),
            setAdvancedFilters: () => buildURL(true),
            setSimpleFilters: () => buildURL(true),
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

            if (params.simpleFilters || params.advancedFilters) {
                if (params.simpleFilters && !equal(params.simpleFilters, values.simpleFilters)) {
                    actions.setSimpleFilters(params.simpleFilters)
                }
                if (params.advancedFilters && !equal(params.advancedFilters, values.advancedFilters)) {
                    actions.setAdvancedFilters(params.advancedFilters)
                }
                // support links that might still contain the old `filters` key
            } else if (params.filters) {
                if (!equal(params.filters, values.filters)) {
                    actions.setAdvancedFilters(params.filters)
                    actions.setSimpleFilters(DEFAULT_SIMPLE_RECORDING_FILTERS)
                }
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
