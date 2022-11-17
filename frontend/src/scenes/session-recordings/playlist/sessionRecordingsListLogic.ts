import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import api, { PaginatedResponse } from 'lib/api'
import { toParams } from 'lib/utils'
import {
    PropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    RecordingFilters,
    SessionRecordingId,
    SessionRecordingPropertiesType,
    SessionRecordingsResponse,
    SessionRecordingType,
} from '~/types'
import type { sessionRecordingsListLogicType } from './sessionRecordingsListLogicType'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import equal from 'fast-deep-equal'
import { dayjs } from 'lib/dayjs'
import { loaders } from 'kea-loaders'

export type PersonUUID = string
interface Params {
    filters?: RecordingFilters
}

interface HashParams {
    sessionRecordingId?: SessionRecordingId
}

export const PLAYLIST_LIMIT = 20

export const DEFAULT_RECORDING_FILTERS: RecordingFilters = {
    session_recording_duration: {
        type: PropertyFilterType.Recording,
        key: 'duration',
        value: 60,
        operator: PropertyOperator.GreaterThan,
    },
    properties: [],
    events: [],
    actions: [],
    date_from: dayjs().subtract(21, 'days').format('YYYY-MM-DD'),
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
                              ...(eventFilter.properties?.filter(({ key }: PropertyFilter) => key !== property) ?? []),
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

export interface SessionRecordingListLogicProps {
    key: string
    personUUID?: PersonUUID
    filters?: RecordingFilters
    updateSearchParams?: boolean
    isStatic?: boolean
}

export const sessionRecordingsListLogic = kea<sessionRecordingsListLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsListLogic', key]),
    props({} as SessionRecordingListLogicProps),
    key((props) => `${props.key}-${props.updateSearchParams ?? '-with-search'}`),
    connect({
        actions: [
            eventUsageLogic,
            ['reportRecordingsListFetched', 'reportRecordingsListPropertiesFetched', 'reportRecordingsListFilterAdded'],
        ],
    }),
    actions({
        getSessionRecordings: true,
        setFilters: (filters: Partial<RecordingFilters>) => ({ filters }),
        replaceFilters: (filters: RecordingFilters) => ({ filters }),
        setShowFilters: (showFilters: boolean) => ({ showFilters }),
        setSelectedRecordingId: (id: SessionRecordingType['id'] | null) => ({
            id,
        }),
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
                        limit: PLAYLIST_LIMIT,
                    }
                    const params = toParams(paramsDict)
                    await breakpoint(100) // Debounce for lots of quick filter changes

                    const startTime = performance.now()
                    const response = await api.recordings.list(params)
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListFetched(loadTimeMs)

                    breakpoint()
                    return response
                },
            },
        ],
        sessionRecordingsPropertiesResponse: [
            {
                results: [],
            } as PaginatedResponse<SessionRecordingPropertiesType>,
            {
                getSessionRecordingsProperties: async (_, breakpoint) => {
                    if (values.sessionRecordingsResponse.results.length < 1) {
                        return {
                            results: [],
                        }
                    }
                    const paramsDict = {
                        session_ids: values.sessionRecordingsResponse.results.map(({ id }) => id),
                    }
                    const params = toParams(paramsDict)
                    await breakpoint(100) // Debounce for lots of quick filter changes

                    const startTime = performance.now()
                    const response = await api.recordings.listProperties(params)
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListPropertiesFetched(loadTimeMs)

                    breakpoint()
                    return response
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        filters: [
            props.filters || DEFAULT_RECORDING_FILTERS,
            {
                replaceFilters: (_, { filters }) => filters,
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
                    return [...sessionRecordingsResponse.results]
                },
                setSelectedRecordingId: (prevSessionRecordings, { id }) => {
                    return [
                        ...prevSessionRecordings.map((s) => {
                            if (s.id === id) {
                                return {
                                    ...s,
                                    viewed: true,
                                }
                            } else {
                                return { ...s }
                            }
                        }),
                    ]
                },
            },
        ],
        selectedRecordingId: [
            null as SessionRecordingType['id'] | null,
            {
                setSelectedRecordingId: (_, { id }) => id ?? null,
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setFilters: () => {
            actions.getSessionRecordings()
        },
        replaceFilters: () => {
            actions.getSessionRecordings()
        },
        loadNext: () => {
            actions.setFilters({
                offset: (values.filters?.offset || 0) + PLAYLIST_LIMIT,
            })
        },
        loadPrev: () => {
            actions.setFilters({
                offset: Math.max((values.filters?.offset || 0) - PLAYLIST_LIMIT, 0),
            })
        },
        getSessionRecordingsSuccess: () => {
            actions.getSessionRecordingsProperties({})
        },
    })),
    selectors({
        sessionRecordingIdToProperties: [
            (s) => [s.sessionRecordingsPropertiesResponse],
            (propertiesResponse: PaginatedResponse<SessionRecordingPropertiesType>) => {
                return (
                    Object.fromEntries(propertiesResponse.results.map(({ id, properties }) => [id, properties])) ?? {}
                )
            },
        ],
        activeSessionRecording: [
            (s) => [s.selectedRecordingId, s.sessionRecordings],
            (selectedRecordingId, sessionRecordings): Partial<SessionRecordingType> | undefined => {
                return selectedRecordingId
                    ? sessionRecordings.find((sessionRecording) => sessionRecording.id === selectedRecordingId) || {
                          id: selectedRecordingId,
                      }
                    : sessionRecordings[0]
            },
        ],
        nextSessionRecording: [
            (s) => [s.activeSessionRecording, s.sessionRecordings],
            (activeSessionRecording, sessionRecordings): Partial<SessionRecordingType> | undefined => {
                if (!activeSessionRecording) {
                    return
                }
                const activeSessionRecordingIndex = sessionRecordings.findIndex(
                    (x) => x.id === activeSessionRecording.id
                )
                return sessionRecordings[activeSessionRecordingIndex + 1]
            },
        ],

        hasPrev: [(s) => [s.filters], (filters) => (filters.offset || 0) > 0],
        hasNext: [
            (s) => [s.sessionRecordingsResponse],
            (sessionRecordingsResponse) => sessionRecordingsResponse.has_next,
        ],
        totalFiltersCount: [
            (s) => [s.filters],
            (filters) =>
                (filters?.actions?.length || 0) + (filters?.events?.length || 0) + (filters?.properties?.length || 0),
        ],
    }),

    afterMount(({ actions }) => {
        actions.getSessionRecordings()
    }),

    actionToUrl(({ props, values }) => {
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
            const params: Params = props.updateSearchParams
                ? {
                      filters: values.filters,
                  }
                : {}
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
            loadSessionRecordings: () => buildURL(true),
            setSelectedRecordingId: () => buildURL(false),
            setFilters: () => buildURL(true),
        }
    }),

    urlToAction(({ actions, values, props }) => {
        const urlToAction = (_: any, params: Params, hashParams: HashParams): void => {
            const nulledSessionRecordingId = hashParams.sessionRecordingId ?? null
            if (nulledSessionRecordingId !== values.selectedRecordingId) {
                actions.setSelectedRecordingId(nulledSessionRecordingId)
            }

            const filters = params.filters
            if (filters && props.updateSearchParams) {
                if (!equal(filters, values.filters)) {
                    actions.replaceFilters(filters)
                }
            }
        }
        return {
            '*': urlToAction,
        }
    }),
])
