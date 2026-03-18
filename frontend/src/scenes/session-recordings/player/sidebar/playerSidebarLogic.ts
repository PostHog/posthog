import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { SessionRecordingSidebarTab } from '~/types'

import type { playerSidebarLogicType } from './playerSidebarLogicType'

export const playerSidebarLogic = kea<playerSidebarLogicType>([
    path(() => ['scenes', 'session-recordings', 'player', 'playerSidebarLogic']),

    actions(() => ({
        setTab: (tab: SessionRecordingSidebarTab) => ({ tab }),
    })),

    reducers(() => ({
        activeTab: [
            SessionRecordingSidebarTab.INSPECTOR as SessionRecordingSidebarTab,
            { setTab: (_, { tab }) => tab },
        ],
    })),

    actionToUrl(() => ({
        setTab: ({ tab }) => {
            const { currentLocation } = router.values
            return [
                currentLocation.pathname,
                {
                    ...currentLocation.searchParams,
                    tab,
                },
                currentLocation.hashParams,
            ]
        },
    })),

    urlToAction(({ actions, values }) => ({
        '*': (_, searchParams, hashParams) => {
            const isShowingRecording =
                Object.keys(searchParams).includes('sessionRecordingId') ||
                Object.keys(hashParams).includes('sessionRecordingId')
            const urlTab = Object.values(SessionRecordingSidebarTab).includes(searchParams.tab)
                ? (searchParams.tab as SessionRecordingSidebarTab)
                : Object.values(SessionRecordingSidebarTab).includes(hashParams.tab)
                  ? (hashParams.tab as SessionRecordingSidebarTab)
                  : null

            if (isShowingRecording && urlTab && urlTab !== values.activeTab) {
                actions.setTab(urlTab)
            }
        },
    })),
])
