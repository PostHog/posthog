import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { TodayMarkedText } from './TodayMarkedText'
import { todayReportLogic } from './todayReportLogic'
import { TodaySectionTitle } from './TodaySectionTitle'

export function TodayReportProposal({ reportId }: { reportId: string }): JSX.Element {
    const { proposal, shownKeyClauses } = useValues(todayReportLogic({ reportId }))
    return (
        <div className="flex flex-col gap-2">
            <TodaySectionTitle>Proposal</TodaySectionTitle>
            {proposal ? (
                <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                    <TodayMarkedText
                        markdown={proposal}
                        marked={[]}
                        keyClauses={shownKeyClauses?.proposal ?? []}
                        reportId={reportId}
                    />
                </Text>
            ) : (
                <Text size="sm" variant="muted" render={<p />}>
                    No fix proposed yet.
                </Text>
            )}
        </div>
    )
}
