import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelCanvasLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelCanvasLogic'
import { NotebookNodeType, SessionRecordingId, SessionRecordingType } from '~/types'

import type { sessionPlayerModalLogicType } from './sessionPlayerModalLogicType'

interface HashParams {
    sessionRecordingId?: SessionRecordingId
}

interface QueryParams {
    timestamp?: number
}

export const sessionPlayerModalLogic = kea<sessionPlayerModalLogicType>([
    path(['scenes', 'session-recordings', 'sessionPlayerModalLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [sidePanelCanvasLogic, ['openCanvas']],
    }),

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

    selectors({
        isSidepanelEnabled: [(s) => [s.featureFlags], (featureFlags) => featureFlags[FEATURE_FLAGS.SIDEPANEL_CANVAS]],
    }),

    listeners(({ actions, values }) => ({
        openSessionPlayer: ({ sessionRecording, initialTimestamp }) => {
            if (values.isSidepanelEnabled) {
                actions.openCanvas('Session Replay', [
                    {
                        type: NotebookNodeType.Recording,
                        attrs: {
                            id: sessionRecording.id,
                            autoPlay: true,
                        },
                    },
                ])
            }
        },
    })),
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

            return [router.values.location.pathname, searchParams, hashParams, { replace }]
        }

        return {
            openSessionPlayer: () => buildURL(false),
            closeSessionPlayer: () => buildURL(false),
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
