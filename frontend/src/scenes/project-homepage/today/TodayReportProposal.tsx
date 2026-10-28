import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { hasActiveReportPullRequest } from 'products/signals/frontend/inbox/utils/reportPullRequests'

import { TodayMarkedText } from './TodayMarkedText'
import { todayReportLogic } from './todayReportLogic'
import { TodaySectionTitle } from './TodaySectionTitle'

export function TodayReportProposal({ reportId }: { reportId: string }): JSX.Element | null {
    const { proposal, shownKeyClauses, currentReport, reportState } = useValues(todayReportLogic({ reportId }))
    if (!proposal && reportState !== 'open') {
        return null
    }
    return (
        <div className="flex flex-col gap-2">
            <TodaySectionTitle>{proposal ? 'Proposal' : 'Next step'}</TodaySectionTitle>
            {proposal ? (
                <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                    <TodayMarkedText
                        markdown={proposal}
                        marked={[]}
                        keyClauses={shownKeyClauses?.proposal ?? []}
                        reportId={reportId}
                    />
                </Text>
            ) : hasActiveReportPullRequest(currentReport) ? (
                <Text size="sm" variant="muted" render={<p />}>
                    A fix is ready for review.
                </Text>
            ) : null}
        </div>
    )
}
