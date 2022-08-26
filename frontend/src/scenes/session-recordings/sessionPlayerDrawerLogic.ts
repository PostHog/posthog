import { actions, connect, kea, path, reducers } from 'kea'
import { SessionRecordingId } from '~/types'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { eventUsageLogic, RecordingWatchedSource } from 'lib/utils/eventUsageLogic'

import type { sessionPlayerDrawerLogicType } from './sessionPlayerDrawerLogicType'
import { sessionRecordingDataLogic } from './player/sessionRecordingDataLogic'
import { subscriptions } from 'kea-subscriptions'

interface HashParams {
    sessionRecordingId?: SessionRecordingId
}

export const sessionPlayerDrawerLogic = kea<sessionPlayerDrawerLogicType>([
    path(['scenes', 'session-recordings', 'sessionPlayerDrawerLogic']),
    connect({
        actions: [eventUsageLogic, ['reportRecordingsListFetched', 'reportRecordingsListFilterAdded']],
    }),
    actions({
        openSessionPlayer: (sessionRecordingId: SessionRecordingId | null, source: RecordingWatchedSource) => ({
            sessionRecordingId,
            source,
        }),
        closeSessionPlayer: true,
    }),
    reducers({
        activeSessionRecordingId: [
            null as SessionRecordingId | null,
            {
                openSessionPlayer: (_, { sessionRecordingId }) => sessionRecordingId,
                closeSessionPlayer: () => null,
            },
        ],
    }),
    subscriptions({
        activeSessionRecordingId: (sessionRecordingId, oldSessionRecordingId) => {
            if (sessionRecordingId !== oldSessionRecordingId) {
                if (sessionRecordingId) {
                    if (!sessionRecordingDataLogic({ sessionRecordingId }).isMounted()) {
                        sessionRecordingDataLogic({ sessionRecordingId }).mount()
                    }
                    sessionRecordingDataLogic({ sessionRecordingId }).actions.loadEntireRecording()
                }
            }
        },
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
            const nulledSessionRecordingId = hashParams.sessionRecordingId ?? null
            if (nulledSessionRecordingId !== values.activeSessionRecordingId) {
                actions.openSessionPlayer(nulledSessionRecordingId, RecordingWatchedSource.Direct)
            }
        }
        return {
            '*': urlToAction,
        }
    }),
])
