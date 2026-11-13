import { useActions, useValues } from 'kea'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { dataQualityOverviewLogic } from './dataQualityOverviewLogic'

export function RunAllBanners(): JSX.Element {
    const { overviewError, snapshotLoaded, startingRun, isRunning, runTarget, pollTimedOut, runError } =
        useValues(dataQualityOverviewLogic)
    const { retryRun, loadOverview } = useActions(dataQualityOverviewLogic)

    const runningAll = (startingRun || isRunning) && runTarget?.kind === 'all'

    return (
        <>
            {overviewError && snapshotLoaded && (
                <LemonBanner type="warning" action={{ children: 'Retry', onClick: loadOverview }}>
                    Couldn't refresh checks. Showing the latest available results.
                </LemonBanner>
            )}
            {runningAll && (
                <LemonBanner type="info" icon={<Spinner />}>
                    Running checks...
                </LemonBanner>
            )}
            {pollTimedOut && runTarget?.kind === 'all' && (
                <LemonBanner type="warning" action={{ children: 'Refresh', onClick: loadOverview }}>
                    Checks are still running. Check back in a few minutes.
                </LemonBanner>
            )}
            {runError && runTarget?.kind === 'all' && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: retryRun }}>
                    {runError}
                </LemonBanner>
            )}
        </>
    )
}
