import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { TodayInlineMarkdown } from './TodayInlineMarkdown'
import { todayReportLogic } from './todayReportLogic'
import { TodayReportSectionTitle } from './TodayReportSectionTitle'

export function TodayReportProposal({ reportId }: { reportId: string }): JSX.Element {
    const { proposal } = useValues(todayReportLogic({ reportId }))
    return (
        <div className="flex flex-col gap-2">
            <TodayReportSectionTitle>Proposal</TodayReportSectionTitle>
            {proposal ? (
                <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                    <TodayInlineMarkdown markdown={proposal} />
                </Text>
            ) : (
                <Text size="sm" variant="muted" render={<p />}>
                    No fix proposed yet.
                </Text>
            )}
        </div>
    )
}
