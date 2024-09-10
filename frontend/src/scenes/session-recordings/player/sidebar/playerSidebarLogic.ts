import { actions, kea, key, path, props, reducers } from 'kea'

import { SessionRecordingSidebarTab } from '~/types'

import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import type { playerSidebarLogicType } from './playerSidebarLogicType'

export const playerSidebarLogic = kea<playerSidebarLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playerSidebarLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),

    actions(() => ({
        setTab: (tab: SessionRecordingSidebarTab | null) => ({ tab }),
    })),

    reducers(() => ({
        activeTab: [
            SessionRecordingSidebarTab.INSPECTOR as SessionRecordingSidebarTab | null,
            { setTab: (_, { tab }) => tab },
        ],
    })),
])
