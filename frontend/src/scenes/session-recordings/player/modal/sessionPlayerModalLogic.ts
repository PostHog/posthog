import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { SessionRecordingId, SessionRecordingType } from '~/types'

import type { sessionPlayerModalLogicType } from './sessionPlayerModalLogicType'

interface HashParams {
    sessionRecordingId?: SessionRecordingId
}

interface QueryParams {
    timestamp?: number
}

export const sessionPlayerModalLogic = kea<sessionPlayerModalLogicType>([
    path(['scenes', 'session-recordings', 'sessionPlayerModalLogic']),
    actions({
        openSessionPlayer: (
            sessionRecording: Pick<SessionRecordingType, 'id' | 'matching_events'>,
            initialTimestamp: number | null = null
        ) => ({
            sessionRecording,
            initialTimestamp,
        }),
        closeSessionPlayer: true,
    }),
    reducers({
        activeSessionRecording: [
            null as Pick<SessionRecordingType, 'id' | 'matching_events'> | null,
            {
                openSessionPlayer: (_, { sessionRecording }) => sessionRecording,
                closeSessionPlayer: () => null,
            },
        ],
        initialTimestamp: [
            null as number | null,
            {
                openSessionPlayer: (_, { initialTimestamp }) => initialTimestamp,
                closeSessionPlayer: () => null,
            },
        ],
    }),
    actionToUrl(({ values }) => {
        const buildURL = (): [
            string,
            Record<string, any>,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            const hashParams: HashParams = {
                ...router.values.hashParams,
            }
            const searchParams: QueryParams = {
                ...router.values.searchParams,
            }

            if (!values.activeSessionRecording?.id) {
                delete hashParams.sessionRecordingId
            } else {
                hashParams.sessionRecordingId = values.activeSessionRecording.id
            }

            if (!values.initialTimestamp) {
                delete searchParams.timestamp
            } else {
                searchParams.timestamp = values.initialTimestamp
            }

            return [router.values.location.pathname, searchParams, hashParams, { replace: true }]
        }

        return {
            openSessionPlayer: () => buildURL(),
            closeSessionPlayer: () => buildURL(),
        }
    }),
    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, searchParams: QueryParams, hashParams: HashParams): void => {
            // Check if the logic is still mounted. Because this is called on every URL change, the logic might have been unmounted already.
            if (sessionPlayerModalLogic.isMounted()) {
                const nulledSessionRecordingId = hashParams.sessionRecordingId ?? null
                const initialTimestamp = searchParams.timestamp ?? null
                if (nulledSessionRecordingId && nulledSessionRecordingId !== values.activeSessionRecording?.id) {
                    actions.openSessionPlayer({ id: nulledSessionRecordingId }, initialTimestamp)
                }
            }
        }
        return {
            '*': urlToAction,
        }
    }),
])
