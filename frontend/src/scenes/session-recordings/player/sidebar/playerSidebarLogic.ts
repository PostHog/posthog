import { actions, kea, path, props, reducers } from 'kea'
import { SessionRecordingPlayerLogicProps } from 'scenes/session-recordings/types'

import { SessionRecordingSidebarTab } from '~/types'

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
])
