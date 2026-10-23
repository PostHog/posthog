import { useActions, useMountedLogic, useValues } from 'kea'
import { ReactNode } from 'react'

import { WatchPicksList } from 'products/replay_vision/frontend/replay_scanners/components/WatchPicksList'
import { watchPicksLogic } from 'products/replay_vision/frontend/replay_scanners/watchPicksLogic'
import { watchPicksStarterLogic } from 'products/replay_vision/frontend/replay_scanners/watchPicksStarterLogic'

import { ReplayListColumn } from './ReplayListColumn'

export function ReplayListColumnWithPicks({
    logicKey,
    recordingsList,
}: {
    logicKey: string
    recordingsList: ReactNode
}): JSX.Element {
    const picksLogic = useMountedLogic(watchPicksLogic)
    const { effectiveListMode, unwatchedCount } = useValues(picksLogic)
    const { setListMode } = useActions(picksLogic)
    useMountedLogic(watchPicksStarterLogic(picksLogic.props))

    return (
        <ReplayListColumn
            logicKey={logicKey}
            recordingsList={recordingsList}
            picksList={<WatchPicksList />}
            picksMode={effectiveListMode}
            unwatchedPicksCount={unwatchedCount}
            onPicksSelected={(selected) => setListMode(selected ? 'picks' : 'recordings')}
        />
    )
}
