import { useActions, useMountedLogic, useValues } from 'kea'
import { ReactNode } from 'react'

import { HighlightPicksList } from 'products/replay_vision/frontend/replay_scanners/components/HighlightPicksList'
import { highlightPicksLogic } from 'products/replay_vision/frontend/replay_scanners/highlightPicksLogic'
import { highlightPicksStarterLogic } from 'products/replay_vision/frontend/replay_scanners/highlightPicksStarterLogic'

import { ReplayListColumn } from './ReplayListColumn'

export function ReplayListColumnWithPicks({
    logicKey,
    recordingsList,
    collections,
}: {
    logicKey: string
    recordingsList: ReactNode
    collections?: boolean
}): JSX.Element {
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const { effectiveListMode, unwatchedCount } = useValues(picksLogic)
    const { setListMode } = useActions(picksLogic)
    useMountedLogic(highlightPicksStarterLogic(picksLogic.props))

    return (
        <ReplayListColumn
            logicKey={logicKey}
            recordingsList={recordingsList}
            collections={collections}
            picksList={<HighlightPicksList />}
            picksMode={effectiveListMode}
            unwatchedPicksCount={unwatchedCount}
            onPicksSelected={(selected) => setListMode(selected ? 'picks' : 'recordings')}
        />
    )
}
