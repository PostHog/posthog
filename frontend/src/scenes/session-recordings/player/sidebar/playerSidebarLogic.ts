import { actions, kea, path, props, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { SessionRecordingSidebarTab } from '~/types'

import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import type { playerSidebarLogicType } from './playerSidebarLogicType'

export const playerSidebarLogic = kea<playerSidebarLogicType>([
    path(() => ['scenes', 'session-recordings', 'player', 'playerSidebarLogic']),
    props({} as SessionRecordingPlayerLogicProps),

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
        ['**/replay/home*']: (_, searchParams) => {
            const urlTab = Object.values(SessionRecordingSidebarTab).includes(searchParams.tab)
                ? (searchParams.tab as SessionRecordingSidebarTab)
                : SessionRecordingSidebarTab.INSPECTOR

            if (!!urlTab && urlTab !== values.activeTab) {
                actions.setTab(urlTab)
            }
        },
    })),
])
