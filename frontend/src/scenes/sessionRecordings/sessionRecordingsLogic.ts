import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { SessionRecordingType } from '~/types'
import { sessionRecordingsTableLogicType } from './sessionRecordingsLogicType'
import { router } from 'kea-router'

type SessionRecordingId = string
interface Params {
    properties?: any
    sessionRecordingId?: SessionRecordingId
}

export const sessionRecordingsTableLogic = kea<sessionRecordingsTableLogicType<SessionRecordingId>>({
    key: (props) => props.personIds || 'global',
    props: {} as {
        personIds?: string[]
    },
    actions: {
        getSessionRecordings: true,
        setSessionRecordingId: (sessionRecordingId: SessionRecordingId | null) => ({ sessionRecordingId }),
        closeSessionPlayer: true,
    },
    loaders: ({ props }) => ({
        sessionRecordings: [
            [] as SessionRecordingType[],
            {
                getSessionRecordings: async () => {
                    const params = toParams({
                        distinct_id: props.personIds ? props.personIds[0] : '',
                    })
                    const response = await api.get(`api/projects/@current/session_recordings?${params}`)
                    return response.results
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
                setSessionRecordingId: (_, { sessionRecordingId }) => sessionRecordingId,
                closeSessionPlayer: () => null,
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
            setSessionRecordingId: () => buildURL(),
            closeSessionPlayer: () => buildURL({ sessionRecordingId: undefined }),
        }
    },

    urlToAction: ({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            const nulledSessionRecordingId = params.sessionRecordingId ?? null
            if (nulledSessionRecordingId !== values.sessionRecordingId) {
                actions.setSessionRecordingId(nulledSessionRecordingId)
            }
        }

        return {
            '/session_recordings': urlToAction,
            '/person/*': urlToAction,
        }
    },
})
