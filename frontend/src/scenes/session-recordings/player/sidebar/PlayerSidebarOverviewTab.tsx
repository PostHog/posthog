import { useValues } from 'kea'

import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { playerMetaLogic } from '../player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarOverviewGrid } from './PlayerSidebarOverviewGrid'
import { PlayerSidebarOverviewOtherWatchers } from './PlayerSidebarOverviewOtherWatchers'

export function PlayerSidebarOverviewTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson } = useValues(playerMetaLogic(logicProps))

    return (
        <div className="bg-primary deprecated-space-y-1 flex h-full flex-col overflow-auto px-2 py-1">
            <PersonDisplay person={sessionPerson} withIcon withCopyButton placement="bottom" />
            <PlayerSidebarOverviewGrid />
            <PlayerSidebarOverviewOtherWatchers />
        </div>
    )
}
