import { kea } from 'kea'
import api from 'lib/api'
import dayjs, { Dayjs } from 'dayjs'
import equal from 'fast-deep-equal'
import { toParams } from 'lib/utils'
import { sessionsTableLogicType } from './sessionsTableLogicType'
import { EventType, PropertyFilter, SessionsPropertyFilter, SessionType } from '~/types'
import { router } from 'kea-router'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import { teamLogic } from '../teamLogic'

type SessionRecordingId = string

export enum ExpandState {
    Expanded,
    Collapsed,
}

interface Params {
    date?: string
    properties?: any
    sessionRecordingId?: SessionRecordingId
    filters?: Array<SessionsPropertyFilter>
    source?: RecordingWatchedSource
}

export const sessionsTableLogic = kea<sessionsTableLogicType<SessionRecordingId>>({
    key: (props) => props.personIds || 'global',
    props: {} as {
        personIds?: string[]
    },
    connect: {
        values: [sessionsFiltersLogic, ['filters']],
        actions: [sessionsFiltersLogic, ['setAllFilters', 'removeFilter']],
    },
    loaders: ({ actions, values, props }) => ({
        sessions: {
            __default: [] as SessionType[],
            loadSessions: async (_: any, breakpoint) => {
                const { selectedDateURLparam } = values
                const params = toParams({
                    date_from: selectedDateURLparam,
                    date_to: selectedDateURLparam,
                    offset: 0,
                    distinct_id: props.personIds ? props.personIds[0] : '',
                    filters: values.filters,
                    properties: values.properties,
                })
                await breakpoint(10)
                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/events/sessions/?${params}`
                )
                breakpoint()
                actions.setPagination(response.pagination)
                return response.result
            },
        },
    }),
    actions: () => ({
        setPagination: (pagination: Record<string, any> | null) => ({ pagination }),
        fetchNextSessions: true,
        appendNewSessions: (sessions) => ({ sessions }),
        previousDay: true,
        nextDay: true,
        applyFilters: true,
        setFilters: (properties: PropertyFilter[], selectedDate: Dayjs | null) => ({
            properties,
            selectedDate,
        }),
        setSessionRecordingId: (sessionRecordingId: SessionRecordingId | null, source?: RecordingWatchedSource) => ({
            sessionRecordingId,
            source,
        }),
        closeSessionPlayer: true,
        loadSessionEvents: (session: SessionType) => ({ session }),
        addSessionEvents: (session: SessionType, events: EventType[]) => ({ session, events }),
        setLastAppliedFilters: (filters: SessionsPropertyFilter[]) => ({ filters }),
        toggleExpandSessionRows: true,
        onExpandedRowsChange: true,
        setShowOnlyMatches: (showOnlyMatches: boolean) => ({ showOnlyMatches }),
    }),
    reducers: {
        sessions: {
            appendNewSessions: (state, { sessions }) => [...state, ...sessions],
            loadSessionsFailure: () => [],
        },
        isLoadingNext: [false, { fetchNextSessions: () => true, appendNewSessions: () => false }],
        pagination: [
            null as Record<string, any> | null,
            {
                setPagination: (_, { pagination }) => pagination,
                loadSessionsFailure: () => null,
            },
        ],
        selectedDate: [null as null | Dayjs, { setFilters: (_, { selectedDate }) => selectedDate }],
        properties: [
            [] as PropertyFilter[],
            {
                setFilters: (_, { properties }) => properties,
            },
        ],
        sessionRecordingId: [
            null as SessionRecordingId | null,
            {
                setSessionRecordingId: (_, { sessionRecordingId }) => sessionRecordingId,
                closeSessionPlayer: () => null,
            },
        ],
        loadedSessionEvents: [
            {} as Record<string, EventType[] | undefined>,
            {
                addSessionEvents: (state, { session, events }) => ({
                    ...state,
                    [session.global_session_id]: events,
                }),
            },
        ],
        lastAppliedFilters: [
            [] as SessionsPropertyFilter[],
            {
                setLastAppliedFilters: (_, { filters }) => filters,
            },
        ],
        rowExpandState: [
            ExpandState.Collapsed,
            {
                toggleExpandSessionRows: (state) =>
                    state === ExpandState.Expanded ? ExpandState.Collapsed : ExpandState.Expanded,
            },
        ],
        manualRowExpansion: [
            true,
            {
                onExpandedRowsChange: () => true,
                toggleExpandSessionRows: () => false,
            },
        ],
        showOnlyMatches: [
            false,
            {
                setShowOnlyMatches: (_, { showOnlyMatches }) => showOnlyMatches,
            },
        ],
    },
    selectors: {
        selectedDateURLparam: [(s) => [s.selectedDate], (selectedDate) => selectedDate?.format('YYYY-MM-DD')],
        orderedSessionRecordingIds: [
            (selectors) => [selectors.sessions],
            (sessions: SessionType[]): SessionRecordingId[] =>
                Array.from(new Set(sessions.flatMap((session) => session.session_recordings.map(({ id }) => id)))),
        ],
        firstRecordingId: [
            (selectors) => [selectors.orderedSessionRecordingIds],
            (ids: SessionRecordingId[]): SessionRecordingId | null => ids[0] || null,
        ],
        filtersDirty: [
            (selectors) => [selectors.filters, selectors.lastAppliedFilters],
            (filters, lastFilters): boolean => !equal(filters, lastFilters),
        ],
        // :NOTE: This recalculates whenever opening a new session or loading new sessions. Memoize per-session instead.
        filteredSessionEvents: [
            (selectors) => [selectors.loadedSessionEvents, selectors.sessions, selectors.showOnlyMatches],
            (
                loadedSessionEvents: Record<string, EventType[] | undefined>,
                sessions: SessionType[],
                showOnlyMatches: boolean
            ): Record<string, EventType[] | undefined> => {
                if (!showOnlyMatches) {
                    return loadedSessionEvents
                }

                return Object.fromEntries(
                    sessions.map((session) => {
                        const events = loadedSessionEvents[session.global_session_id]
                        const matchingEvents = new Set(session.matching_events)
                        return [session.global_session_id, events?.filter((e) => matchingEvents.has(e.id))]
                    })
                )
            },
        ],
        expandedRowKeysProps: [
            (selectors) => [selectors.sessions, selectors.rowExpandState, selectors.manualRowExpansion],
            (
                sessions,
                rowExpandState,
                manualRowExpansion
            ): {
                expandedRowKeys?: string[]
            } => {
                if (manualRowExpansion) {
                    return {}
                } else if (rowExpandState === ExpandState.Collapsed) {
                    return { expandedRowKeys: [] }
                } else {
                    return { expandedRowKeys: sessions.map((s) => s.global_session_id) || [] }
                }
            },
        ],
    },
    listeners: ({ values, actions, props }) => ({
        fetchNextSessions: async (_, breakpoint) => {
            const params = toParams({
                date_from: values.selectedDateURLparam,
                date_to: values.selectedDateURLparam,
                pagination: values.pagination,
                distinct_id: props.personIds ? props.personIds[0] : '',
                filters: values.filters,
                properties: values.properties,
            })
            const response = await api.get(`api/projects/${teamLogic.values.currentTeamId}/events/sessions/?${params}`)
            breakpoint()
            actions.setPagination(response.pagination)
            actions.appendNewSessions(response.result)
        },
        applyFilters: () => {
            actions.setPagination(null)
            actions.loadSessions(true)
            actions.setLastAppliedFilters(values.filters)
        },
        setFilters: () => {
            actions.setPagination(null)
            actions.loadSessions(true)
        },
        previousDay: () => {
            actions.setFilters(values.properties, dayjs(values.selectedDate || undefined).add(-1, 'day'))
        },
        nextDay: () => {
            actions.setFilters(values.properties, dayjs(values.selectedDate || undefined).add(1, 'day'))
        },
        loadSessionEvents: async ({ session }, breakpoint) => {
            if (!values.loadedSessionEvents[session.global_session_id]) {
                const params = {
                    distinct_id: session.distinct_id,
                    date_from: session.start_time,
                    date_to: session.end_time,
                }

                await breakpoint(200)

                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/events/session_events?${toParams(params)}`
                )
                actions.addSessionEvents(session, response.result)
            }
        },
        removeFilter: () => {
            // Apply empty filters if there are no filters to display. User cannot manually
            // trigger an apply because the Filters panel is hidden if there are no filters.
            if (values.filters.length === 0) {
                actions.applyFilters()
            }
        },
    }),
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
            const today = dayjs().startOf('day').format('YYYY-MM-DD')

            const { properties } = router.values.searchParams

            const params: Params = {
                date: values.selectedDateURLparam !== today ? values.selectedDateURLparam : undefined,
                properties: properties || undefined,
                sessionRecordingId: values.sessionRecordingId || undefined,
                filters: values.filters,
                ...overrides,
            }

            return [router.values.location.pathname, params, router.values.hashParams, { replace }]
        }

        return {
            setFilters: () => buildURL({}, true),
            loadSessions: () => buildURL({}, true),
            setSessionRecordingId: ({ source }) => buildURL({ source }),
            closeSessionPlayer: () => buildURL({ sessionRecordingId: undefined }),
        }
    },
    urlToAction: ({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            const newDate = params.date ? dayjs(params.date).startOf('day') : dayjs().startOf('day')

            if (
                JSON.stringify(params.properties || []) !== JSON.stringify(values.properties) ||
                !values.selectedDate ||
                values.selectedDate.format('YYYY-MM-DD') !== newDate.format('YYYY-MM-DD')
            ) {
                actions.setFilters(params.properties || [], newDate)
            } else if (values.sessions.length === 0 && !values.sessionsLoading) {
                actions.loadSessions(true)
            }

            if (params.sessionRecordingId !== values.sessionRecordingId) {
                actions.setSessionRecordingId(
                    params.sessionRecordingId ?? null,
                    params.source || RecordingWatchedSource.Direct
                )
            }

            if (JSON.stringify(params.filters || {}) !== JSON.stringify(values.filters)) {
                actions.setAllFilters(params.filters || [])
                actions.applyFilters()
            }
        }

        return {
            '/sessions': urlToAction,
            '/person/*': (_: any, params: Params) => {
                // Needed while the REMOVE_SESSIONS feature flag exists. Otherwise, this logic and
                // the sessionRecordingsLogic both try to set the sessionRecordingId
                // query param, and we end up with multiple navigations to the player page
                if (!featureFlagLogic.values.featureFlags[FEATURE_FLAGS.REMOVE_SESSIONS]) {
                    urlToAction(_, params)
                }
            },
        }
    },
})
