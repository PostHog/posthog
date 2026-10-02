import { useValues } from 'kea'

import { inboxReportDetailLogic } from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayReportContinue } from './TodayReportContinue'

export function TodayReportLiveContinue({
    report,
    reportUrl,
}: {
    report: SignalReport
    reportUrl: string
}): JSX.Element {
    const { implementationSlotClaim, reportTaskToOpen } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    return (
        <TodayReportContinue
            report={report}
            reportUrl={reportUrl}
            reportTaskToOpen={reportTaskToOpen}
            implementationSlotClaim={implementationSlotClaim}
        />
    )
}
