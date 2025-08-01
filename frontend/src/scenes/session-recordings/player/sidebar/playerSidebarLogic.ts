import { actions, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { SessionRecordingSidebarTab } from '~/types'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { userLogic } from 'scenes/userLogic'
import { membersLogic } from 'scenes/organization/membersLogic'

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

    selectors(() => ({
        sessionPlayerMetaData: [
            () => [sessionRecordingPlayerLogic.selectors.sessionPlayerMetaData],
            (sessionPlayerMetaData) => sessionPlayerMetaData,
        ],
        currentUser: [() => [userLogic.selectors.user], (user) => user],
        members: [() => [membersLogic.selectors.members], (members) => members],
        viewers: [
            (s) => [s.sessionPlayerMetaData, s.currentUser],
            (sessionPlayerMetaData, currentUser) => {
                return sessionPlayerMetaData?.viewers?.filter((viewer) => viewer !== currentUser?.email) || []
            },
        ],
        viewerMembers: [
            (s) => [s.viewers, s.members],
            (viewers, members) => {
                return viewers.map((viewer) => {
                    const member = members?.find((m) => m.user.email === viewer)
                    return member?.user || { email: viewer }
                })
            },
        ],
        viewerCount: [(s) => [s.viewers], (viewers) => viewers.length],
        hasOtherViewers: [(s) => [s.viewerCount], (viewerCount) => viewerCount > 0],
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
