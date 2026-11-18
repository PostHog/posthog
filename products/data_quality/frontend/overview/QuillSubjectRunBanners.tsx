import { useActions, useValues } from 'kea'

import { QuillCheckCallout } from '../QuillCheckCallout'
import { SubjectGroup, dataQualityOverviewLogic } from './dataQualityOverviewLogic'

export function QuillSubjectRunBanners({ group }: { group: SubjectGroup }): JSX.Element | null {
    const { runTarget, runError, pollTimedOut } = useValues(dataQualityOverviewLogic)
    const { retryRun, loadOverview } = useActions(dataQualityOverviewLogic)

    const scopedToThisSubject = runTarget?.kind === 'subject' && runTarget.subjectKey === group.subjectKey
    if (!scopedToThisSubject) {
        return null
    }

    return (
        <>
            {pollTimedOut && (
                <QuillCheckCallout tone="warning" action={{ label: 'Refresh', onClick: loadOverview }}>
                    Checks are still running. Check back in a few minutes.
                </QuillCheckCallout>
            )}
            {runError && (
                <QuillCheckCallout tone="destructive" action={{ label: 'Retry', onClick: retryRun }}>
                    {runError}
                </QuillCheckCallout>
            )}
        </>
    )
}
