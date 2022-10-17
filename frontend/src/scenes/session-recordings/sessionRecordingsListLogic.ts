import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import {
    AnyPropertyFilter,
    EntityTypes,
    FilterType,
    PropertyOperator,
    RecordingDurationFilter,
    RecordingFilters,
    SessionRecordingId,
    SessionRecordingsResponse,
} from '~/types'
import type { sessionRecordingsListLogicType } from './sessionRecordingsListLogicType'
import { router } from 'kea-router'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import equal from 'fast-deep-equal'
import { teamLogic } from '../teamLogic'
import { dayjs } from 'lib/dayjs'
import { SessionRecordingType } from '~/types'

export type PersonUUID = string
interface Params {
    filters?: RecordingFilters
}

interface HashParams {
    sessionRecordingId?: SessionRecordingId
}

export const PLAYLIST_LIMIT = 20

export const DEFAULT_DURATION_FILTER: RecordingDurationFilter = {
    type: 'recording',
    key: 'duration',
    value: 60,
    operator: PropertyOperator.GreaterThan,
}

export const DEFAULT_PROPERTY_FILTERS = []

export const DEFAULT_ENTITY_FILTERS = {
    events: [],
    actions: [],
    new_entity: [
        {
            id: 'empty',
            type: EntityTypes.NEW_ENTITY,
            order: 0,
            name: 'empty',
        },
    ],
}

export interface SessionRecordingTableLogicProps {
    personUUID?: PersonUUID
    key?: string
}

export const sessionRecordingsListLogic = kea<sessionRecordingsListLogicType>({
    path: (key) => ['scenes', 'session-recordings', 'sessionRecordingsListLogic', key],
    props: {} as SessionRecordingTableLogicProps,
    key: (props) => `${props.key || props.personUUID || 'global'}`,
    connect: {
        values: [teamLogic, ['currentTeamId']],
        actions: [eventUsageLogic, ['reportRecordingsListFetched', 'reportRecordingsListFilterAdded']],
    },
    actions: {
        getSessionRecordings: true,
        setSelectedRecordingId: (id: SessionRecordingType['id'] | null) => ({
            id,
        }),
        setEntityFilters: (filters: Partial<FilterType>) => ({ filters }),
        setPropertyFilters: (filters: AnyPropertyFilter[]) => {
            return { filters }
        },
        loadNext: true,
        loadPrev: true,
        setFiltersEnabled: (showing: boolean) => ({ showing }),
        setOffset: (offset: number) => ({ offset }),
        setDateRange: (incomingFromDate: string | undefined, incomingToDate: string | undefined) => ({
            incomingFromDate,
            incomingToDate,
        }),
        setDurationFilter: (durationFilter: RecordingDurationFilter) => ({ durationFilter }),
    },
    loaders: ({ props, values, actions }) => ({
        sessionRecordingsResponse: [
            {
                results: [],
                has_next: false,
            } as SessionRecordingsResponse,
            {
                getSessionRecordings: async (_, breakpoint) => {
                    const paramsDict = {
                        ...values.filterQueryParams,
                        person_uuid: props.personUUID ?? '',
                        limit: PLAYLIST_LIMIT,
                    }
                    const params = toParams(paramsDict)
                    await breakpoint(100) // Debounce for lots of quick filter changes

                    const startTime = performance.now()
                    const response = await api.get(`api/projects/${values.currentTeamId}/session_recordings?${params}`)
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListFetched(loadTimeMs)

                    breakpoint()
                    return response
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.getSessionRecordings()
        },
    }),
    reducers: ({}) => ({
        filtersEnabled: [
            false,
            {
                setFiltersEnabled: (_, { showing }) => showing,
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
        entityFilters: [
            DEFAULT_ENTITY_FILTERS as FilterType,
            {
                setEntityFilters: (_, { filters }) => ({ ...filters }),
            },
        ],
        propertyFilters: [
            DEFAULT_PROPERTY_FILTERS as AnyPropertyFilter[],
            {
                setPropertyFilters: (_, { filters }) => [...filters],
            },
        ],
        durationFilter: [
            DEFAULT_DURATION_FILTER as RecordingDurationFilter,
            {
                setDurationFilter: (_, { durationFilter }) => durationFilter,
            },
        ],
        offset: [
            0,
            {
                loadNext: (previousOffset) => previousOffset + PLAYLIST_LIMIT,
                loadPrev: (previousOffset) => Math.max(previousOffset - PLAYLIST_LIMIT, 0),
                setOffset: (_, { offset }) => offset,
            },
        ],
        fromDate: [
            dayjs().subtract(21, 'days').format('YYYY-MM-DD') as null | string,
            {
                setDateRange: (_, { incomingFromDate }) => incomingFromDate ?? null,
            },
        ],
        toDate: [
            null as string | null,
            {
                setDateRange: (_, { incomingToDate }) => incomingToDate ?? null,
            },
        ],
    }),
    listeners: ({ actions }) => ({
        setEntityFilters: () => {
            actions.getSessionRecordings()
        },
        setPropertyFilters: () => {
            actions.getSessionRecordings()
        },
        setDateRange: () => {
            actions.getSessionRecordings()
        },
        setDurationFilter: () => {
            actions.getSessionRecordings()
        },
        loadNext: () => {
            actions.getSessionRecordings()
        },
        loadPrev: () => {
            actions.getSessionRecordings()
        },
    }),
    selectors: {
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
        hasPrev: [(s) => [s.offset], (offset) => offset > 0],
        hasNext: [
            (s) => [s.sessionRecordingsResponse],
            (sessionRecordingsResponse) => sessionRecordingsResponse.has_next,
        ],
        filterQueryParams: [
            (s) => [s.entityFilters, s.fromDate, s.toDate, s.offset, s.durationFilter, s.propertyFilters],
            (entityFilters, fromDate, toDate, offset, durationFilter, propertyFilters) => {
                return {
                    actions: entityFilters.actions,
                    events: entityFilters.events,
                    properties: propertyFilters,
                    date_from: fromDate,
                    date_to: toDate,
                    offset: offset,
                    session_recording_duration: durationFilter,
                }
            },
        ],
    },
    actionToUrl: ({ values }) => {
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
                filters: values.filterQueryParams,
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
            loadSessionRecordings: () => buildURL(true),
            setSelectedRecordingId: () => buildURL(false),
            setEntityFilters: () => buildURL(true),
            setPropertyFilters: () => buildURL(true),
            setDateRange: () => buildURL(true),
            setDurationFilter: () => buildURL(true),
            loadNext: () => buildURL(true),
            loadPrev: () => buildURL(true),
        }
    },

    urlToAction: ({ actions, values, props }) => {
        const urlToAction = (_: any, params: Params, hashParams: HashParams): void => {
            const nulledSessionRecordingId = hashParams.sessionRecordingId ?? null
            if (nulledSessionRecordingId !== values.selectedRecordingId) {
                actions.setSelectedRecordingId(nulledSessionRecordingId)
            }

            const filters = params.filters
            if (filters) {
                if (
                    !equal(filters.actions, values.entityFilters.actions) ||
                    !equal(filters.events, values.entityFilters.events)
                ) {
                    actions.setEntityFilters({
                        events: filters.events || [],
                        actions: filters.actions || [],
                    })
                }
                if (!equal(filters.properties, values.propertyFilters)) {
                    actions.setPropertyFilters(filters.properties ?? [])
                }
                if (filters.date_from !== values.fromDate || filters.date_to !== values.toDate) {
                    actions.setDateRange(filters.date_from ?? undefined, filters.date_to ?? undefined)
                }
                if (filters.offset !== values.offset) {
                    actions.setOffset(filters.offset ?? 0)
                }
                if (!equal(filters.session_recording_duration, values.durationFilter)) {
                    actions.setDurationFilter(filters.session_recording_duration ?? DEFAULT_DURATION_FILTER)
                }
            }
        }
        const urlPattern = props.personUUID ? '/person/*' : '/recordings'
        return {
            [urlPattern]: urlToAction,
        }
    },
})
