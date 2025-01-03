import { PersonDisplay } from '@posthog/apps-common'
import { useValues } from 'kea'
import { PlayerSidebarSessionSummary } from 'scenes/session-recordings/player/sidebar/PlayerSidebarSessionSummary'

import { playerMetaLogic } from '../playerMetaLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarOverviewGrid } from './PlayerSidebarOverviewGrid'

export function PlayerSidebarOverviewTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson } = useValues(playerMetaLogic(logicProps))

    return (
        <div className="flex flex-col overflow-auto bg-bg-3000 px-2 py-1 h-full space-y-1">
            <PersonDisplay person={sessionPerson} withIcon withCopyButton />
            <PlayerSidebarOverviewGrid />
            <PlayerSidebarSessionSummary />
        </div>
    )
}
