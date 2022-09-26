import { actions, kea, path, reducers } from 'kea'
import { SessionRecordingId, SessionRecordingType } from '~/types'
import { actionToUrl, router, urlToAction } from 'kea-router'
import type { sessionPlayerDrawerLogicType } from './sessionPlayerDrawerLogicType'

interface HashParams {
    sessionRecordingId?: SessionRecordingId
}

export const sessionPlayerDrawerLogic = kea<sessionPlayerDrawerLogicType>([
    path(['scenes', 'session-recordings', 'sessionPlayerDrawerLogic']),
    actions({
        openSessionPlayer: (sessionRecording: Pick<SessionRecordingType, 'id' | 'matching_events'>) => ({
            sessionRecording,
        }),
        closeSessionPlayer: true,
    }),
    reducers({
        activeSessionRecordingId: [
            null as SessionRecordingId | null,
            {
                openSessionPlayer: (_, { sessionRecording }) => sessionRecording?.id,
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

            if (!values.activeSessionRecordingId) {
                delete hashParams.sessionRecordingId
            } else {
                hashParams.sessionRecordingId = values.activeSessionRecordingId
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
            if (sessionPlayerDrawerLogic.isMounted()) {
                const nulledSessionRecordingId = hashParams.sessionRecordingId ?? null
                if (nulledSessionRecordingId && nulledSessionRecordingId !== values.activeSessionRecordingId) {
                    actions.openSessionPlayer({ id: nulledSessionRecordingId })
                }
            }
        }
        return {
            '*': urlToAction,
        }
    }),
])
