import { actions, connect, kea, path, reducers } from 'kea'
import { SessionRecordingsTabs } from '~/types'
import { urls } from 'scenes/urls'
import { actionToUrl, router, urlToAction } from 'kea-router'

import type { sessionRecordingsLogicType } from './sessionRecordingsLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export const sessionRecordingsLogic = kea<sessionRecordingsLogicType>([
    path(() => ['scenes', 'session-recordings', 'root']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setTab: (tab: SessionRecordingsTabs = SessionRecordingsTabs.Recent) => ({ tab }),
    }),
    reducers(({}) => ({
        tab: [
            SessionRecordingsTabs.Recent as SessionRecordingsTabs,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    })),
    actionToUrl(({ values }) => {
        return {
            setTab: () => urls.sessionRecordings(values.tab),
        }
    }),

    urlToAction(({ actions, values }) => {
        return {
            '/recordings': () => {
                if (!values.featureFlags[FEATURE_FLAGS.RECORDING_PLAYLISTS]) {
                    return
                }
                router.actions.replace(urls.sessionRecordings(SessionRecordingsTabs.Recent))
            },
            '/recordings/:tab': ({ tab }) => {
                if (!values.featureFlags[FEATURE_FLAGS.RECORDING_PLAYLISTS]) {
                    return
                }

                if (tab !== values.tab) {
                    actions.setTab(tab as SessionRecordingsTabs)
                }
            },
        }
    }),
])
