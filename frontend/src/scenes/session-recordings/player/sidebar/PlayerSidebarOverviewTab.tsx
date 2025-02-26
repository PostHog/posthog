import { useValues } from 'kea'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { PlayerSidebarSessionSummary } from 'scenes/session-recordings/player/sidebar/PlayerSidebarSessionSummary'

import { playerMetaLogic } from '../player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarOverviewGrid } from './PlayerSidebarOverviewGrid'
import { PlayerSidebarOverviewOtherWatchers } from './PlayerSidebarOverviewOtherWatchers'

export function PlayerSidebarOverviewTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson } = useValues(playerMetaLogic(logicProps))

    return (
        <div className="flex flex-col overflow-auto bg-primary px-2 py-1 h-full space-y-1">
            <PersonDisplay person={sessionPerson} withIcon withCopyButton placement="bottom" />
            <PlayerSidebarOverviewGrid />
            <PlayerSidebarOverviewOtherWatchers />
            <PlayerSidebarSessionSummary />
        </div>
    )
}
