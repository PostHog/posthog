import { useActions, useValues } from 'kea'

import { QuillCheckCallout } from '../QuillCheckCallout'
import { dataQualityOverviewLogic } from './dataQualityOverviewLogic'

export function QuillRunAllBanners(): JSX.Element {
    const { overviewError, snapshotLoaded, startingRun, isRunning, runTarget, pollTimedOut, runError } =
        useValues(dataQualityOverviewLogic)
    const { retryRun, loadOverview } = useActions(dataQualityOverviewLogic)

    const runningAll = (startingRun || isRunning) && runTarget?.kind === 'all'

    return (
        <>
            {overviewError && snapshotLoaded && (
                <QuillCheckCallout tone="warning" action={{ label: 'Retry', onClick: loadOverview }}>
                    Couldn't refresh checks. Showing the latest available results.
                </QuillCheckCallout>
            )}
            {runningAll && (
                <QuillCheckCallout tone="info" busy>
                    Running checks...
                </QuillCheckCallout>
            )}
            {pollTimedOut && runTarget?.kind === 'all' && (
                <QuillCheckCallout tone="warning" action={{ label: 'Refresh', onClick: loadOverview }}>
                    Checks are still running. Check back in a few minutes.
                </QuillCheckCallout>
            )}
            {runError && runTarget?.kind === 'all' && (
                <QuillCheckCallout tone="destructive" action={{ label: 'Retry', onClick: retryRun }}>
                    {runError}
                </QuillCheckCallout>
            )}
        </>
    )
}
