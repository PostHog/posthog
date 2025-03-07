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
        // intentionally locked to replay/* to prevent other pages from setting the tab
        // this is a debug affordance
        ['**/replay/*']: (_, searchParams) => {
            const urlTab = Object.values(SessionRecordingSidebarTab).includes(searchParams.tab)
                ? (searchParams.tab as SessionRecordingSidebarTab)
                : SessionRecordingSidebarTab.INSPECTOR

            if (urlTab !== values.activeTab) {
                actions.setTab(urlTab)
            }
        },
    })),
])
