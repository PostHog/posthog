import { useValues } from 'kea'

import { Heading, Text } from '@posthog/quill'

import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayEvidenceAge } from './TodayEvidenceAge'
import { TodayMarkedText } from './TodayMarkedText'
import { todayReportLogic } from './todayReportLogic'
import { reportTitle } from './todaySignalReports'

export function TodayReportTitle({ report }: { report: SignalReport }): JSX.Element {
    const { lead, leadMarks, shownKeyClauses } = useValues(todayReportLogic({ reportId: report.id }))
    const stillInvestigating = !report.summary?.trim()

    return (
        <div className="flex flex-col gap-2">
            <Heading size="xl" render={<h1 />} className="leading-snug text-balance">
                {reportTitle(report)}
            </Heading>
            {lead && (
                <div data-today-figures>
                    <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                        <TodayMarkedText
                            markdown={lead}
                            marked={leadMarks}
                            keyClauses={shownKeyClauses?.lead ?? []}
                            reportId={report.id}
                        />
                    </Text>
                </div>
            )}
            {stillInvestigating && (
                <Text variant="muted" render={<p />}>
                    No summary yet. An agent is still investigating.
                </Text>
            )}
            <TodayEvidenceAge report={report} />
        </div>
    )
}
