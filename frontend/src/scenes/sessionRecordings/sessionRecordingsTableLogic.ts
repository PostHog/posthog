import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import {
    EntityTypes,
    FilterType,
    PropertyOperator,
    RecordingDurationFilter,
    RecordingFilters,
    SessionRecordingsResponse,
} from '~/types'
import { sessionRecordingsTableLogicType } from './sessionRecordingsTableLogicType'
import { router } from 'kea-router'
import dayjs from 'dayjs'
import { RecordingWatchedSource } from 'lib/utils/eventUsageLogic'

export type SessionRecordingId = string
export type PersonUUID = string
interface Params {
    filters?: RecordingFilters
    sessionRecordingId?: SessionRecordingId
    source?: RecordingWatchedSource
}

const LIMIT = 50

export const DEFAULT_ENTITY_FILTERS = {
    events: [],
    actions: [],
    new_entity: [
        {
            id: null,
            type: EntityTypes.EVENTS,
            order: 0,
            name: null,
        },
    ],
}

export const sessionRecordingsTableLogic = kea<sessionRecordingsTableLogicType<PersonUUID, SessionRecordingId>>({
    key: (props) => props.personUUID || 'global',
    props: {} as {
        personUUID?: PersonUUID
    },
    actions: {
        getSessionRecordings: true,
        openSessionPlayer: (sessionRecordingId: SessionRecordingId | null, source: RecordingWatchedSource) => ({
            sessionRecordingId,
            source,
        }),
        closeSessionPlayer: true,
        setEntityFilters: (filters: Partial<FilterType>) => ({ filters }),
        loadNext: true,
        loadPrev: true,
        enableEntityFilter: true,
        setOffset: (offset: number) => ({ offset }),
        setDateRange: (incomingFromDate: string | undefined, incomingToDate: string | undefined) => ({
            incomingFromDate,
            incomingToDate,
        }),
        setDurationFilter: (durationFilter: RecordingDurationFilter) => ({ durationFilter }),
    },
    loaders: ({ props, values }) => ({
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
                        limit: LIMIT,
                    }
                    const params = toParams(paramsDict)
                    await breakpoint(100) // Debounce for lots of quick filter changes
                    const response = await api.get(`api/projects/@current/session_recordings?${params}`)
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
    reducers: {
        entityFilterEnabled: [
            false,
            {
                enableEntityFilter: () => true,
            },
        ],
        sessionRecordings: [
            [],
            {
                getSessionRecordingsSuccess: (_, { sessionRecordingsResponse }) => {
                    return [...sessionRecordingsResponse.results]
                },
                openSessionPlayer: (sessionRecordings, { sessionRecordingId }) => {
                    return [
                        ...sessionRecordings.map((sessionRecording) => {
                            if (sessionRecording.id === sessionRecordingId) {
                                return {
                                    ...sessionRecording,
                                    viewed: true,
                                }
                            } else {
                                return { ...sessionRecording }
                            }
                        }),
                    ]
                },
            },
        ],
        sessionRecordingId: [
            null as SessionRecordingId | null,
            {
                openSessionPlayer: (_, { sessionRecordingId }) => sessionRecordingId,
                closeSessionPlayer: () => null,
            },
        ],
        entityFilters: [
            DEFAULT_ENTITY_FILTERS as FilterType,
            {
                setEntityFilters: (_, { filters }) => ({ ...filters }),
            },
        ],
        durationFilter: [
            {
                type: 'recording',
                key: 'duration',
                value: 60,
                operator: PropertyOperator.GreaterThan,
            } as RecordingDurationFilter,
            {
                setDurationFilter: (_, { durationFilter }) => durationFilter,
            },
        ],
        offset: [
            0,
            {
                loadNext: (previousOffset) => previousOffset + LIMIT,
                loadPrev: (previousOffset) => Math.max(previousOffset - LIMIT),
                setOffset: (_, { offset }) => offset,
            },
        ],
        fromDate: [
            dayjs().subtract(30, 'days').format('YYYY-MM-DD') as null | string,
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
    },
    listeners: ({ actions }) => ({
        setEntityFilters: () => {
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
        hasPrev: [(s) => [s.offset], (offset) => offset > 0],
        hasNext: [
            (s) => [s.sessionRecordingsResponse],
            (sessionRecordingsResponse) => sessionRecordingsResponse.has_next,
        ],
        showEntityFilter: [
            (s) => [s.entityFilterEnabled, s.entityFilters],
            (entityFilterEnabled, entityFilters) => {
                return entityFilterEnabled || entityFilters !== DEFAULT_ENTITY_FILTERS
            },
        ],
        filterQueryParams: [
            (s) => [s.entityFilters, s.fromDate, s.toDate, s.offset, s.durationFilter],
            (entityFilters, fromDate, toDate, offset, durationFilter) => {
                return {
                    actions: entityFilters.actions,
                    events: entityFilters.events,
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
            overrides: Partial<Params> = {},
            replace = false
        ): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            }
        ] => {
            const params: Params = {
                sessionRecordingId: values.sessionRecordingId || undefined,
                filters: values.filterQueryParams,
                ...overrides,
            }
            return [router.values.location.pathname, params, router.values.hashParams, { replace }]
        }

        return {
            loadSessionRecordings: () => buildURL({}, true),
            openSessionPlayer: ({ source }) => buildURL({ source }),
            closeSessionPlayer: () => buildURL({ sessionRecordingId: undefined }),
            setEntityFilters: () => buildURL({}, true),
            setDateRange: () => buildURL({}, true),
            setDurationFilter: () => buildURL({}, true),
            loadNext: () => buildURL({}, true),
            loadPrev: () => buildURL({}, true),
        }
    },

    urlToAction: ({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            const nulledSessionRecordingId = params.sessionRecordingId ?? null
            if (nulledSessionRecordingId !== values.sessionRecordingId) {
                actions.openSessionPlayer(nulledSessionRecordingId, RecordingWatchedSource.Direct)
            }

            const filters = params.filters
            if (filters) {
                if ((filters.actions && filters.actions.length > 0) || (filters.events && filters.events.length > 0)) {
                    actions.setEntityFilters({
                        events: filters.events || [],
                        actions: filters.actions || [],
                    })
                }
                if (filters.date_from || filters.date_to) {
                    actions.setDateRange(filters.date_from ?? undefined, filters.date_to ?? undefined)
                }
                if (filters.offset) {
                    actions.setOffset(filters.offset)
                }
                if (filters.session_recording_duration) {
                    actions.setDurationFilter(filters.session_recording_duration)
                }
            }
        }

        return {
            '/recordings': urlToAction,
            '/person/*': urlToAction,
        }
    },
})
