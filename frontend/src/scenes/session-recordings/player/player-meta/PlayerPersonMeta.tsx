import './PlayerMeta.scss'

import { useActions, useValues } from 'kea'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { PersonIcon } from 'scenes/persons/PersonDisplay'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'

import { SessionRecordingSidebarTab } from '~/types'

import { playerSettingsLogic } from '../playerSettingsLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { playerSidebarLogic } from '../sidebar/playerSidebarLogic'

export function PlayerPersonMeta(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson } = useValues(playerMetaLogic(logicProps))

    const { setTab } = useActions(playerSidebarLogic)
    const { setSidebarOpen } = useActions(playerSettingsLogic)
    const { sidebarOpen } = useValues(playerSettingsLogic)

    const onClick = (): void => {
        setSidebarOpen(!sidebarOpen)
        setTab(SessionRecordingSidebarTab.OVERVIEW)
    }

    return (
        <div className="PlayerMeta__top flex items-center gap-1 shrink-0 cursor-pointer" onClick={onClick}>
            {!sessionPerson ? (
                <LemonSkeleton.Circle className="w-8 h-8" />
            ) : (
                <PersonIcon person={sessionPerson} size="md" className="mr-0" />
            )}
        </div>
    )
}
