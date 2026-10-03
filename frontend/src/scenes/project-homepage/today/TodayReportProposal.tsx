import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { SignalReport } from 'products/signals/frontend/inbox/types'

import { renderedText } from './todayKeyClauses'
import { TodayMarkedText } from './TodayMarkedText'
import { todayReportLogic } from './todayReportLogic'
import { TodayReportSections, reportProposal } from './todayReportPresentation'
import { TodayReportSectionTitle } from './TodayReportSectionTitle'

export function TodayReportProposal({
    report,
    sections,
}: {
    report: SignalReport
    sections: TodayReportSections
}): JSX.Element {
    const { keyClauses } = useValues(todayReportLogic({ reportId: report.id }))
    const proposal = reportProposal(report, sections)
    return (
        <div className="flex flex-col gap-2">
            <TodayReportSectionTitle>Proposal</TodayReportSectionTitle>
            {proposal ? (
                <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                    <TodayMarkedText
                        markdown={proposal}
                        marked={[]}
                        reportId={report.id}
                        keyClauses={keyClauses[renderedText(proposal)]}
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
