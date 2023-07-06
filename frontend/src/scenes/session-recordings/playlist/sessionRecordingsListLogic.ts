import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import api from 'lib/api'
import { objectClean, toParams } from 'lib/utils'
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
import posthog from 'posthog-js'

export type PersonUUID = string

interface Params {
    filters?: RecordingFilters
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
    console_logs: [],
}

const DEFAULT_PERSON_RECORDING_FILTERS: RecordingFilters = {
    ...DEFAULT_RECORDING_FILTERS,
    date_from: '-21d',
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
        setShowFilters: (showFilters: boolean) => ({ showFilters }),
        resetFilters: true,
        setSelectedRecordingId: (id: SessionRecordingType['id'] | null) => ({
            id,
        }),
        loadAllRecordings: true,
        loadPinnedRecordings: true,
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
                loadSessionRecordings: async ({ direction }, breakpoint) => {
                    const paramsDict = {
                        ...values.filters,
                        person_uuid: props.personUUID ?? '',
                        limit: RECORDINGS_LIMIT,
                        version: values.listingVersion,
                    }

                    if (direction === 'older') {
                        paramsDict['date_to'] =
                            values.sessionRecordings[values.sessionRecordings.length - 1]?.start_time
                    }

                    if (direction === 'newer') {
                        paramsDict['date_from'] = values.sessionRecordings[0]?.start_time
                    }

                    const params = toParams(paramsDict)

                    await breakpoint(100) // Debounce for lots of quick filter changes

                    const startTime = performance.now()
                    const response = await api.recordings.list(params)
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListFetched(loadTimeMs, values.listingVersion)

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
        customFilters: [
            (props.filters ?? null) as RecordingFilters | null,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                resetFilters: () => null,
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
            posthog.capture('recording list filters changed', { ...partialFilters })
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
        shouldShowEmptyState: [
            (s) => [s.sessionRecordings, s.customFilters, s.sessionRecordingsResponseLoading],
            (sessionRecordings, customFilters, sessionRecordingsResponseLoading): boolean => {
                return !sessionRecordingsResponseLoading && sessionRecordings.length === 0 && !customFilters
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

    // NOTE: It is important this comes after urlToAction, as it will override the default behavior
    afterMount(({ actions }) => {
        actions.loadSessionRecordings()
        actions.loadPinnedRecordings()
    }),
])
