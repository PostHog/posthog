import { actions, kea, path, props, reducers } from 'kea'

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
])
