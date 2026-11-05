import { useValues } from 'kea'

import { inboxReportDetailLogic } from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import type { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayReportBody } from './TodayReportBody'

export function TodayReportLiveBody({
    report,
    linksToInbox,
}: {
    report: SignalReport
    linksToInbox?: boolean
}): JSX.Element {
    const { implementationSlotClaim, reportTaskToOpen } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    return (
        <TodayReportBody
            report={report}
            live={{ reportTaskToOpen, implementationSlotClaim }}
            linksToInbox={linksToInbox}
        />
    )
}
