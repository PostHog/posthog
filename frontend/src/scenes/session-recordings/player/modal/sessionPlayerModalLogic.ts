import { actions, kea, path, reducers } from 'kea'
import { SessionRecordingId, SessionRecordingType } from '~/types'
import { actionToUrl, router, urlToAction } from 'kea-router'

import type { sessionPlayerModalLogicType } from './sessionPlayerModalLogicType'

interface HashParams {
    sessionRecordingId?: SessionRecordingId
}

export const sessionPlayerModalLogic = kea<sessionPlayerModalLogicType>([
    path(['scenes', 'session-recordings', 'sessionPlayerModalLogic']),
    actions({
        openSessionPlayer: (sessionRecording: Pick<SessionRecordingType, 'id' | 'matching_events'>) => ({
            sessionRecording,
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
    }),
    actionToUrl(({ values }) => {
        const buildURL = (
            replace: boolean
        ): [
            string,
            Record<string, any>,
            Record<string, any>,
            {
                replace: boolean
            }
        ] => {
            const hashParams: HashParams = {
                ...router.values.hashParams,
            }

            if (!values.activeSessionRecording?.id) {
                delete hashParams.sessionRecordingId
            } else {
                hashParams.sessionRecordingId = values.activeSessionRecording.id
            }

            return [router.values.location.pathname, router.values.searchParams, hashParams, { replace }]
        }

        return {
            openSessionPlayer: ({}) => buildURL(false),
            closeSessionPlayer: () => buildURL(false),
        }
    }),
    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, __: any, hashParams: HashParams): void => {
            // Check if the logic is still mounted. Because this is called on every URL change, the logic might have been unmounted already.
            if (sessionPlayerModalLogic.isMounted()) {
                const nulledSessionRecordingId = hashParams.sessionRecordingId ?? null
                if (nulledSessionRecordingId && nulledSessionRecordingId !== values.activeSessionRecording?.id) {
                    actions.openSessionPlayer({ id: nulledSessionRecordingId })
                }
            }
        }
        return {
            '*': urlToAction,
        }
    }),
])
