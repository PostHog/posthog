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

interface Params {
    filters?: RecordingFilters
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

export const RECORDINGS_LIMIT = 20
export const PINNED_RECORDINGS_LIMIT = 100 // NOTE: This is high but avoids the need for pagination for now...

export const defaultRecordingDurationFilter: RecordingDurationFilter = {
    type: PropertyFilterType.Recording,
    key: 'duration',
    value: 1,
    operator: PropertyOperator.GreaterThan,
}

export const DEFAULT_RECORDING_FILTERS: RecordingFilters = {
    session_recording_duration: defaultRecordingDurationFilter,
    properties: [],
    events: [],
    actions: [],
    date_from: '-7d',
    date_to: null,
    console_logs: [],
}

const DEFAULT_PERSON_RECORDING_FILTERS: RecordingFilters = {
    ...DEFAULT_RECORDING_FILTERS,
    date_from: '-30d',
}

export const getDefaultFilters = (personUUID?: PersonUUID): RecordingFilters => {
    return personUUID ? DEFAULT_PERSON_RECORDING_FILTERS : DEFAULT_RECORDING_FILTERS
}

function isPageViewFilter(filter: Record<string, any>): boolean {
    return filter.name === '$pageview'
}
function isCurrentURLPageViewFilter(eventsFilter: Record<string, any>): boolean {
    const hasSingleProperty = Array.isArray(eventsFilter.properties) && eventsFilter.properties?.length === 1
    const isCurrentURLProperty = hasSingleProperty && eventsFilter.properties[0].key === '$current_url'
    return isPageViewFilter(eventsFilter) && isCurrentURLProperty
}

// checks are stored against filter keys so that the type system enforces adding a check when we add new filters
const advancedFilterChecks: Record<
    keyof RecordingFilters,
    (filters: RecordingFilters, defaultFilters: RecordingFilters) => boolean
> = {
    actions: (filters) => (filters.actions ? filters.actions.length > 0 : false),
    events: function (filters: RecordingFilters): boolean {
        const eventsFilters = filters.events || []
        // simple filters allow a single $pageview event filter with $current_url as the selected property
        // anything else is advanced
        return (
            eventsFilters.length > 1 ||
            (!!eventsFilters[0] &&
                (!isPageViewFilter(eventsFilters[0]) || !isCurrentURLPageViewFilter(eventsFilters[0])))
        )
    },
    properties: function (): boolean {
        // TODO is this right? should we ever care about properties for choosing between advanced and simple?
        return false
    },
    date_from: (filters, defaultFilters) => filters.date_from != defaultFilters.date_from,
    date_to: (filters, defaultFilters) => filters.date_to != defaultFilters.date_to,
    session_recording_duration: (filters, defaultFilters) =>
        !equal(filters.session_recording_duration, defaultFilters.session_recording_duration),
    duration_type_filter: (filters, defaultFilters) =>
        filters.duration_type_filter !== defaultFilters.duration_type_filter,
    console_search_query: (filters) =>
        filters.console_search_query ? filters.console_search_query.trim().length > 0 : false,
    console_logs: (filters) => (filters.console_logs ? filters.console_logs.length > 0 : false),
    filter_test_accounts: (filters) => filters.filter_test_accounts ?? false,
}

export const addedAdvancedFilters = (
    filters: RecordingFilters | undefined,
    defaultFilters: RecordingFilters
): boolean => {
    // if there are no filters or if some filters are not present then the page is still booting up
    if (!filters || filters.session_recording_duration === undefined || filters.date_from === undefined) {
        return false
    }

    // keeps results with the keys for printing when debugging
    const checkResults = Object.keys(advancedFilterChecks).map((key) => ({
        key,
        result: advancedFilterChecks[key](filters, defaultFilters),
    }))

    // if any check is true, then this is an advanced filter
    return checkResults.some((checkResult) => checkResult.result)
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

export interface SessionRecordingPlaylistLogicProps {
    logicKey?: string
    personUUID?: PersonUUID
    updateSearchParams?: boolean
    autoPlay?: boolean
    filters?: RecordingFilters
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
        setFilters: (filters: Partial<RecordingFilters>) => ({ filters }),
        setShowFilters: (showFilters: boolean) => ({ showFilters }),
        setShowAdvancedFilters: (showAdvancedFilters: boolean) => ({ showAdvancedFilters }),
        setShowSettings: (showSettings: boolean) => ({ showSettings }),
        resetFilters: true,
        setSelectedRecordingId: (id: SessionRecordingType['id'] | null) => ({
            id,
        }),
        loadAllRecordings: true,
        loadPinnedRecordings: true,
        loadSessionRecordings: (direction?: 'newer' | 'older') => ({ direction }),
        maybeLoadSessionRecordings: (direction?: 'newer' | 'older') => ({ direction }),
        summarizeSession: (id: SessionRecordingType['id']) => ({ id }),
        suggestTitle: true,
        loadNext: true,
        loadPrev: true,
        toggleShowOtherRecordings: (show?: boolean) => ({ show }),
    }),
    propsChanged(({ actions, props }, oldProps) => {
        if (!objectsEqual(props.filters, oldProps.filters)) {
            props.filters ? actions.setFilters(props.filters) : actions.resetFilters()
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
        suggestedTitle: {
            suggestTitle: async (): Promise<string> => {
                const recordings = values.otherRecordings.slice(0, 5)
                const summaryResponses = await Promise.all(recordings.map((r) => api.recordings.summarize(r.id)))
                const summaries = summaryResponses.map((r) => r.content)
                const response = await api.recordings.suggestPlaylistTitle(summaries)

                console.log(summaries)
                console.log(response)
                return response
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
        customFilters: [
            props.filters ?? null,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                resetFilters: () => null,
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
        showAdvancedFilters: [
            addedAdvancedFilters(props.filters, getDefaultFilters(props.personUUID)),
            {
                persist: true,
            },
            {
                setFilters: (showingAdvancedFilters, { filters }) => {
                    return addedAdvancedFilters(filters, getDefaultFilters(props.personUUID))
                        ? true
                        : showingAdvancedFilters
                },
                setShowAdvancedFilters: (_, { showAdvancedFilters }) => showAdvancedFilters,
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
                setFilters: () => false,
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

            // capture only the partial filters applied (not the full filters object)
            // take each key from the filter and change it to `partial_filter_chosen_${key}`
            const partialFilters = Object.keys(filters).reduce((acc, key) => {
                acc[`partial_filter_chosen_${key}`] = filters[key]
                return acc
            }, {})

            posthog.capture('recording list filters changed', {
                ...partialFilters,
                showing_advanced_filters: values.showAdvancedFilters,
            })

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
            // If we are at the end of the list then try to load more
            const recordingIndex = values.sessionRecordings.findIndex((s) => s.id === values.selectedRecordingId)
            if (recordingIndex === values.sessionRecordings.length - 1) {
                actions.maybeLoadSessionRecordings('older')
            }
        },
    })),
    selectors({
        logicProps: [() => [(_, props) => props], (props): SessionRecordingPlaylistLogicProps => props],
        shouldShowEmptyState: [
            (s) => [
                s.sessionRecordings,
                s.customFilters,
                s.sessionRecordingsResponseLoading,
                s.sessionRecordingsAPIErrored,
                (_, props) => props.personUUID,
            ],
            (
                sessionRecordings,
                customFilters,
                sessionRecordingsResponseLoading,
                sessionRecordingsAPIErrored,
                personUUID
            ): boolean => {
                return (
                    !sessionRecordingsAPIErrored &&
                    !sessionRecordingsResponseLoading &&
                    sessionRecordings.length === 0 &&
                    !customFilters &&
                    !personUUID
                )
            },
        ],

        filters: [
            (s) => [s.customFilters, (_, props) => props.personUUID],
            (customFilters, personUUID): RecordingFilters => {
                const defaultFilters = getDefaultFilters(personUUID)
                return {
                    ...defaultFilters,
                    ...customFilters,
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
                    (filters.console_logs?.length || 0)
                )
            },
        ],
        hasAdvancedFilters: [
            (s) => [s.filters, (_, props) => props.personUUID],
            (filters, personUUID) => {
                const defaultFilters = getDefaultFilters(personUUID)
                return addedAdvancedFilters(filters, defaultFilters)
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
                filters: values.customFilters ?? undefined,
                sessionRecordingId: values.selectedRecordingId ?? undefined,
            })

            // We used to have sessionRecordingId in the hash, so we keep it there for backwards compatibility
            if (router.values.hashParams.sessionRecordingId) {
                delete router.values.hashParams.sessionRecordingId
            }

            return [router.values.location.pathname, params, router.values.hashParams, { replace }]
        }

        return {
            setSelectedRecordingId: () => buildURL(false),
            setFilters: () => buildURL(true),
            resetFilters: () => buildURL(true),
        }
    }),

    urlToAction(({ actions, values, props }) => {
        const urlToAction = (_: any, params: Params, hashParams: Params): void => {
            if (!props.updateSearchParams) {
                return
            }

            // We changed to have the sessionRecordingId in the query params, but it used to be in the hash so backwards compatibility
            const nulledSessionRecordingId = params.sessionRecordingId ?? hashParams.sessionRecordingId ?? null
            if (nulledSessionRecordingId !== values.selectedRecordingId) {
                actions.setSelectedRecordingId(nulledSessionRecordingId)
            }

            if (params.filters) {
                if (!equal(params.filters, values.customFilters)) {
                    actions.setFilters(params.filters)
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
