import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
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
import type { sessionRecordingsListLogicType } from './sessionRecordingsListLogicType'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import equal from 'fast-deep-equal'
import { loaders } from 'kea-loaders'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
import { playerSettingsLogic } from '../player/playerSettingsLogic'

export type PersonUUID = string
interface Params {
    filters?: RecordingFilters
}

interface HashParams {
    sessionRecordingId?: SessionRecordingId
}

export const RECORDINGS_LIMIT = 20
export const PINNED_RECORDINGS_LIMIT = 100 // NOTE: This is high but avoids the need for pagination for now...

export const defaultRecordingDurationFilter: RecordingDurationFilter = {
    type: PropertyFilterType.Recording,
    key: 'duration',
    value: 60,
    operator: PropertyOperator.GreaterThan,
}
export const DEFAULT_RECORDING_FILTERS: RecordingFilters = {
    session_recording_duration: defaultRecordingDurationFilter,
    properties: [],
    events: [],
    actions: [],
    date_from: '-7d',
    date_to: null,
}

const DEFAULT_PERSON_RECORDING_FILTERS: RecordingFilters = {
    ...DEFAULT_RECORDING_FILTERS,
    session_recording_duration: {
        type: PropertyFilterType.Recording,
        key: 'duration',
        value: 1,
        operator: PropertyOperator.GreaterThan,
    },
}

const getDefaultFilters = (personUUID?: PersonUUID): RecordingFilters => {
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

export function generateSessionRecordingListLogicKey(props: SessionRecordingListLogicProps): string {
    return `${props.key}-${props.playlistShortId}-${props.personUUID}-${props.updateSearchParams ? '-with-search' : ''}`
}

export interface SessionRecordingListLogicProps {
    key?: string
    playlistShortId?: string
    personUUID?: PersonUUID
    filters?: RecordingFilters
    updateSearchParams?: boolean
    autoPlay?: boolean
    onFiltersChange?: (filters: RecordingFilters) => void
}

export const sessionRecordingsListLogic = kea<sessionRecordingsListLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsListLogic', key]),
    props({} as SessionRecordingListLogicProps),
    key(generateSessionRecordingListLogicKey),
    connect({
        actions: [
            eventUsageLogic,
            ['reportRecordingsListFetched', 'reportRecordingsListFilterAdded'],
            sessionRecordingsListPropertiesLogic,
            ['maybeLoadPropertiesForSessions'],
        ],
        values: [featureFlagLogic, ['featureFlags'], playerSettingsLogic, ['autoplayDirection']],
    }),
    actions({
        setFilters: (filters: Partial<RecordingFilters>) => ({ filters }),
        replaceFilters: (filters: RecordingFilters) => ({ filters }),
        setShowFilters: (showFilters: boolean) => ({ showFilters }),
        resetFilters: true,
        setSelectedRecordingId: (id: SessionRecordingType['id'] | null) => ({
            id,
        }),
        loadAllRecordings: true,
        loadPinnedRecordings: true,
        getSessionRecordings: true,
        loadSessionRecordings: (direction?: 'newer' | 'older') => ({ direction }),
        maybeLoadSessionRecordings: (direction?: 'newer' | 'older') => ({ direction }),
        loadNext: true,
        loadPrev: true,
    }),
    loaders(({ props, values, actions }) => ({
        sessionRecordingsResponse: [
            {
                results: [],
                has_next: false,
            } as SessionRecordingsResponse,
            {
                getSessionRecordings: async (_, breakpoint) => {
                    const paramsDict = {
                        ...values.filters,
                        person_uuid: props.personUUID ?? '',
                        limit: RECORDINGS_LIMIT,
                        version: values.listingVersion,
                    }

                    const params = toParams(paramsDict)
                    await breakpoint(100) // Debounce for lots of quick filter changes

                    const startTime = performance.now()
                    const response = await api.recordings.list(params)
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListFetched(loadTimeMs, values.listingVersion)

                    breakpoint()
                    return response
                },

                loadSessionRecordings: async ({ direction }, breakpoint) => {
                    const currentResults = direction ? values.sessionRecordingsResponse?.results ?? [] : []

                    const paramsDict = {
                        ...values.filters,
                        person_uuid: props.personUUID ?? '',
                        limit: RECORDINGS_LIMIT,
                        version: values.listingVersion,
                    }

                    if (direction === 'older') {
                        paramsDict['date_to'] = currentResults[currentResults.length - 1]?.start_time
                    }

                    if (direction === 'newer') {
                        paramsDict['date_from'] = currentResults[0]?.start_time
                    }

                    const params = toParams(paramsDict)

                    await breakpoint(100) // Debounce for lots of quick filter changes

                    const startTime = performance.now()
                    const response = await api.recordings.list(params)
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListFetched(loadTimeMs, values.listingVersion)

                    breakpoint()

                    const mergedResults: SessionRecordingType[] = [...currentResults]

                    response.results.forEach((recording) => {
                        if (!currentResults.find((r) => r.id === recording.id)) {
                            mergedResults.push(recording)
                        }
                    })

                    mergedResults.sort((a, b) => (a.start_time > b.start_time ? -1 : 1))

                    return {
                        has_next:
                            direction === 'newer'
                                ? values.sessionRecordingsResponse?.has_next ?? true
                                : response.has_next,
                        results: mergedResults,
                    }
                },
                setSelectedRecordingId: async ({ id }) => {
                    const existing = [...(values.sessionRecordingsResponse?.results ?? [])]

                    const updatedResults = existing.map((recording) => {
                        if (recording.id === id) {
                            return {
                                ...recording,
                                viewed: true,
                            }
                        }
                        return recording
                    })

                    return {
                        has_next: values.sessionRecordingsResponse.has_next,
                        results: updatedResults,
                    }
                },
            },
        ],
        pinnedRecordingsResponse: [
            null as SessionRecordingsResponse | null,
            {
                loadPinnedRecordings: async (_, breakpoint) => {
                    if (!props.playlistShortId) {
                        return null
                    }

                    const paramsDict = {
                        limit: PINNED_RECORDINGS_LIMIT,
                    }

                    const params = toParams(paramsDict)
                    await breakpoint(100)
                    const response = await api.recordings.listPlaylistRecordings(props.playlistShortId, params)
                    breakpoint()
                    return response
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        filters: [
            props.filters || getDefaultFilters(props.personUUID),
            {
                replaceFilters: (_, { filters }) => {
                    return {
                        ...filters,
                        session_recording_duration:
                            filters.session_recording_duration || defaultRecordingDurationFilter,
                    }
                },
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
            },
        ],
        showFilters: [
            false,
            {
                setShowFilters: (_, { showFilters }) => showFilters,
            },
        ],
        sessionRecordings: [
            [] as SessionRecordingType[],
            {
                getSessionRecordingsSuccess: (_, { sessionRecordingsResponse }) => {
                    return [...(sessionRecordingsResponse?.results ?? [])]
                },
                loadSessionRecordingsSuccess: (_, { sessionRecordingsResponse }) => {
                    return [...(sessionRecordingsResponse?.results ?? [])]
                },
                setSelectedRecordingId: (prevSessionRecordings, { id }) =>
                    prevSessionRecordings.map((s) => {
                        if (s.id === id) {
                            return {
                                ...s,
                                viewed: true,
                            }
                        } else {
                            return { ...s }
                        }
                    }),
            },
        ],
        selectedRecordingId: [
            null as SessionRecordingType['id'] | null,
            {
                setSelectedRecordingId: (_, { id }) => id ?? null,
            },
        ],
    })),
    listeners(({ props, actions, values }) => ({
        loadAllRecordings: () => {
            if (values.featureFlags[FEATURE_FLAGS.SESSION_RECORDING_INFINITE_LIST]) {
                actions.loadSessionRecordings()
            } else {
                actions.getSessionRecordings()
            }
            actions.loadPinnedRecordings()
        },
        setFilters: () => {
            if (values.featureFlags[FEATURE_FLAGS.SESSION_RECORDING_INFINITE_LIST]) {
                actions.loadSessionRecordings()
            } else {
                actions.getSessionRecordings()
            }

            props.onFiltersChange?.(values.filters)
        },
        replaceFilters: () => {
            if (values.featureFlags[FEATURE_FLAGS.SESSION_RECORDING_INFINITE_LIST]) {
                actions.loadSessionRecordings()
            } else {
                actions.getSessionRecordings()
            }
        },
        resetFilters: () => {
            actions.setFilters(getDefaultFilters(props.personUUID))
        },

        loadNext: () => {
            actions.setFilters({
                offset: (values.filters?.offset || 0) + RECORDINGS_LIMIT,
            })
        },
        loadPrev: () => {
            actions.setFilters({
                offset: Math.max((values.filters?.offset || 0) - RECORDINGS_LIMIT, 0),
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

        loadSessionRecordingsSuccess: () => {
            actions.maybeLoadPropertiesForSessions(values.sessionRecordings.map((s) => s.id))
        },

        getSessionRecordingsSuccess: () => {
            actions.maybeLoadPropertiesForSessions(values.sessionRecordings.map((s) => s.id))
        },
        setSelectedRecordingId: () => {
            if (values.featureFlags[FEATURE_FLAGS.SESSION_RECORDING_INFINITE_LIST]) {
                // If we are at the end of the list then try to load more
                const recordingIndex = values.sessionRecordings.findIndex((s) => s.id === values.selectedRecordingId)
                if (recordingIndex === values.sessionRecordings.length - 1) {
                    actions.maybeLoadSessionRecordings('older')
                }
            }
        },
    })),
    selectors({
        listingVersion: [
            (s) => [s.featureFlags],
            (featureFlags): '1' | '2' | '3' => {
                return featureFlags[FEATURE_FLAGS.SESSION_RECORDING_SUMMARY_LISTING]
                    ? '3'
                    : featureFlags[FEATURE_FLAGS.RECORDINGS_LIST_V2]
                    ? '2'
                    : '1'
            },
        ],
        activeSessionRecording: [
            (s) => [s.selectedRecordingId, s.sessionRecordings, (_, props) => props.autoPlay],
            (selectedRecordingId, sessionRecordings, autoPlay): Partial<SessionRecordingType> | undefined => {
                return selectedRecordingId
                    ? sessionRecordings.find((sessionRecording) => sessionRecording.id === selectedRecordingId) || {
                          id: selectedRecordingId,
                      }
                    : autoPlay
                    ? sessionRecordings[0]
                    : undefined
            },
        ],
        nextSessionRecording: [
            (s) => [s.activeSessionRecording, s.sessionRecordings, s.autoplayDirection],
            (
                activeSessionRecording,
                sessionRecordings,
                autoplayDirection
            ): Partial<SessionRecordingType> | undefined => {
                if (!activeSessionRecording || !autoplayDirection) {
                    return
                }
                const activeSessionRecordingIndex = sessionRecordings.findIndex(
                    (x) => x.id === activeSessionRecording.id
                )
                return autoplayDirection === 'older'
                    ? sessionRecordings[activeSessionRecordingIndex + 1]
                    : sessionRecordings[activeSessionRecordingIndex - 1]
            },
        ],

        hasPrev: [(s) => [s.filters], (filters) => (filters.offset || 0) > 0],
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
                        : 1)
                )
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
            const params: Params = {
                filters: values.filters,
            }
            const hashParams: HashParams = {
                ...router.values.hashParams,
            }
            if (!values.selectedRecordingId) {
                delete hashParams.sessionRecordingId
            } else {
                hashParams.sessionRecordingId = values.selectedRecordingId
            }

            return [router.values.location.pathname, params, hashParams, { replace }]
        }

        return {
            getSessionRecordings: () => buildURL(true),
            setSelectedRecordingId: () => buildURL(false),
            setFilters: () => buildURL(true),
        }
    }),

    urlToAction(({ actions, values, props }) => {
        const urlToAction = (_: any, params: Params, hashParams: HashParams): void => {
            if (!props.updateSearchParams) {
                return
            }

            const nulledSessionRecordingId = hashParams.sessionRecordingId ?? null
            if (nulledSessionRecordingId !== values.selectedRecordingId) {
                actions.setSelectedRecordingId(nulledSessionRecordingId)
            }

            if (params.filters) {
                if (!equal(params.filters, values.filters)) {
                    actions.replaceFilters(params.filters)
                }
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    // NOTE: It is important this comes after urlToAction, as it will override the default behavior
    afterMount(({ actions, values }) => {
        if (values.featureFlags[FEATURE_FLAGS.SESSION_RECORDING_INFINITE_LIST]) {
            actions.loadSessionRecordings()
        } else {
            actions.getSessionRecordings()
        }
        actions.loadPinnedRecordings()
    }),
])
