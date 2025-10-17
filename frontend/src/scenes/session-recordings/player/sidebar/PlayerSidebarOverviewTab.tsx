import { useValues } from 'kea'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { playerMetaLogic } from '../player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarOverviewGrid } from './PlayerSidebarOverviewGrid'
import { PlayerSidebarOverviewOtherWatchers } from './PlayerSidebarOverviewOtherWatchers'

export function ResolutionView(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)

    const { resolutionDisplay, scaleDisplay, loading } = useValues(playerMetaLogic(logicProps))

    return loading ? (
        <LemonSkeleton className="w-1/3 h-4" />
    ) : (
        <Tooltip
            placement="bottom"
            title={
                <>
                    The resolution of the page as it was captured was <b>{resolutionDisplay}</b>
                    <br />
                    You are viewing the replay at <b>{scaleDisplay}</b> of the original size
                </>
            }
        >
            <span className="text-secondary text-xs flex flex-row items-center gap-x-1">
                <span>{resolutionDisplay}</span>
                <span>({scaleDisplay})</span>
            </span>
        </Tooltip>
    )
}

export function PlayerSidebarOverviewTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson } = useValues(playerMetaLogic(logicProps))

    return (
        <div className="flex flex-col overflow-auto bg-primary px-2 py-1 h-full deprecated-space-y-1">
            <div className="flex flex-row justify-between">
                <PersonDisplay person={sessionPerson} withIcon withCopyButton placement="bottom" />
                <ResolutionView />
            </div>
            <PlayerSidebarOverviewGrid />
            <PlayerSidebarOverviewOtherWatchers />
        </div>
    )
}
