import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { EntityTypes, FilterType, SessionRecordingType } from '~/types'
import { sessionRecordingsTableLogicType } from './sessionRecordingsTableLogicType'
import { router } from 'kea-router'

type SessionRecordingId = string
interface Params {
    properties?: any
    sessionRecordingId?: SessionRecordingId
}

interface SessionRecordingsResponse {
    results: SessionRecordingType[]
    has_next: boolean
}

const LIMIT = 50

export const sessionRecordingsTableLogic = kea<
    sessionRecordingsTableLogicType<SessionRecordingId, SessionRecordingsResponse>
>({
    key: (props) => props.personUUID || 'global',
    props: {} as {
        personUUID?: string
    },
    actions: {
        getSessionRecordings: true,
        openSessionPlayer: (sessionRecordingId: SessionRecordingId | null) => ({ sessionRecordingId }),
        closeSessionPlayer: true,
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        loadNext: true,
        loadPrev: true,
    },
    loaders: ({ props, values }) => ({
        sessionRecordingsResponse: [
            {
                results: [],
                has_next: false,
            } as SessionRecordingsResponse,
            {
                getSessionRecordings: async () => {
                    const params = toParams({
                        person_uuid: props.personUUID ?? '',
                        actions: values.filters.actions,
                        events: values.filters.events,
                        date_from: 'all',
                        offset: values.offset,
                        limit: LIMIT,
                    })
                    const response = await api.get(`api/projects/@current/session_recordings?${params}`)
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
        sessionRecordingId: [
            null as SessionRecordingId | null,
            {
                openSessionPlayer: (_, { sessionRecordingId }) => sessionRecordingId,
                closeSessionPlayer: () => null,
            },
        ],
        filters: [
            {
                id: null,
                type: EntityTypes.NEW_ENTITY,
                order: 0,
                name: null,
            } as FilterType,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        offset: [
            0,
            {
                loadNext: (previousOffset) => previousOffset + LIMIT,
                loadPrev: (previousOffset) => Math.max(previousOffset - LIMIT),
            },
        ],
    },
    listeners: ({ actions }) => ({
        setFilters: () => {
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
        sessionRecordings: [
            (s) => [s.sessionRecordingsResponse],
            (sessionRecordingsResponse) => sessionRecordingsResponse.results,
        ],
        hasPrev: [(s) => [s.offset], (offset) => offset > 0],
        hasNext: [
            (s) => [s.sessionRecordingsResponse],
            (sessionRecordingsResponse) => sessionRecordingsResponse.has_next,
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
            const { properties } = router.values.searchParams
            const params: Params = {
                properties: properties || undefined,
                sessionRecordingId: values.sessionRecordingId || undefined,
                ...overrides,
            }

            return [router.values.location.pathname, params, router.values.hashParams, { replace }]
        }

        return {
            loadSessionRecordings: () => buildURL({}, true),
            openSessionPlayer: () => buildURL(),
            closeSessionPlayer: () => buildURL({ sessionRecordingId: undefined }),
        }
    },

    urlToAction: ({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            const nulledSessionRecordingId = params.sessionRecordingId ?? null
            if (nulledSessionRecordingId !== values.sessionRecordingId) {
                actions.openSessionPlayer(nulledSessionRecordingId)
            }
        }

        return {
            '/session_recordings': urlToAction,
            '/person/*': urlToAction,
        }
    },
})
