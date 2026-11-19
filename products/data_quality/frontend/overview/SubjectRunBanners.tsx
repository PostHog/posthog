import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { SubjectGroup, dataQualityOverviewLogic } from './dataQualityOverviewLogic'

export function SubjectRunBanners({ group }: { group: SubjectGroup }): JSX.Element | null {
    const { runTarget, runError, pollTimedOut } = useValues(dataQualityOverviewLogic)
    const { retryRun, loadOverview } = useActions(dataQualityOverviewLogic)

    const scopedToThisSubject = runTarget?.kind === 'subject' && runTarget.subjectKey === group.subjectKey
    if (!scopedToThisSubject) {
        return null
    }

    return (
        <>
            {pollTimedOut && (
                <div className="px-2 pb-2">
                    <LemonBanner type="warning" action={{ children: 'Refresh', onClick: loadOverview }}>
                        Checks are still running. Check back in a few minutes.
                    </LemonBanner>
                </div>
            )}
            {runError && (
                <div className="px-2 pb-2">
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Retry',
                            onClick: retryRun,
                        }}
                    >
                        {runError}
                    </LemonBanner>
                </div>
            )}
        </>
    )
}
