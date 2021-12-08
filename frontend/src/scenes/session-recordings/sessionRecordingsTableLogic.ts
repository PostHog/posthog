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
    SessionRecordingsResponse,
} from '~/types'
import { sessionRecordingsTableLogicType } from './sessionRecordingsTableLogicType'
import { router } from 'kea-router'
import { RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import equal from 'fast-deep-equal'
import { teamLogic } from '../teamLogic'
import { dayjs } from 'lib/dayjs'
import { SessionRecordingType } from '~/types'

export type SessionRecordingId = string
export type PersonUUID = string
interface Params {
    filters?: RecordingFilters
    sessionRecordingId?: SessionRecordingId
    source?: RecordingWatchedSource
}

const LIMIT = 50

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
            id: null,
            type: EntityTypes.EVENTS,
            order: 0,
            name: null,
        },
    ],
}

export const sessionRecordingsTableLogic = kea<sessionRecordingsTableLogicType<PersonUUID, SessionRecordingId>>({
    path: (key) => ['scenes', 'session-recordings', 'sessionRecordingsTableLogic', key],
    key: (props) => props.personUUID || 'global',
    props: {} as {
        personUUID?: PersonUUID
    },
    connect: {
        values: [teamLogic, ['currentTeamId']],
    },
    actions: {
        getSessionRecordings: true,
        openSessionPlayer: (sessionRecordingId: SessionRecordingId | null, source: RecordingWatchedSource) => ({
            sessionRecordingId,
            source,
        }),
        closeSessionPlayer: true,
        setEntityFilters: (filters: Partial<FilterType>) => ({ filters }),
        setPropertyFilters: (filters: AnyPropertyFilter[]) => {
            return { filters }
        },
        loadNext: true,
        loadPrev: true,
        enableFilter: true,
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
                    const response = await api.get(`api/projects/${values.currentTeamId}/session_recordings?${params}`)
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
        filterEnabled: [
            false,
            {
                enableFilter: () => true,
            },
        ],
        sessionRecordings: [
            [] as SessionRecordingType[],
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
        propertyFilters: [
            DEFAULT_PROPERTY_FILTERS as AnyPropertyFilter[],
            {
                setPropertyFilters: (_, { filters }) => {
                    console.log('setPropertyFilters', filters)
                    return [...filters]
                },
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
                loadNext: (previousOffset) => previousOffset + LIMIT,
                loadPrev: (previousOffset) => Math.max(previousOffset - LIMIT),
                setOffset: (_, { offset }) => offset,
            },
        ],
        fromDate: [
            dayjs().subtract(7, 'days').format('YYYY-MM-DD') as null | string,
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
        hasPrev: [(s) => [s.offset], (offset) => offset > 0],
        hasNext: [
            (s) => [s.sessionRecordingsResponse],
            (sessionRecordingsResponse) => sessionRecordingsResponse.has_next,
        ],
        showFilters: [
            (s) => [s.filterEnabled, s.entityFilters, s.propertyFilters],
            (filterEnabled, entityFilters, propertyFilters) => {
                return (
                    filterEnabled ||
                    entityFilters !== DEFAULT_ENTITY_FILTERS ||
                    propertyFilters !== DEFAULT_PROPERTY_FILTERS
                )
            },
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
            setPropertyFilters: () => buildURL({}, true),
            setDateRange: () => buildURL({}, true),
            setDurationFilter: () => buildURL({}, true),
            loadNext: () => buildURL({}, true),
            loadPrev: () => buildURL({}, true),
        }
    },

    urlToAction: ({ actions, values, props }) => {
        const urlToAction = (_: any, params: Params): void => {
            const nulledSessionRecordingId = params.sessionRecordingId ?? null
            if (nulledSessionRecordingId !== values.sessionRecordingId) {
                actions.openSessionPlayer(nulledSessionRecordingId, RecordingWatchedSource.Direct)
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
