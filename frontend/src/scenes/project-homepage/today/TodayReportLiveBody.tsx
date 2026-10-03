import { useValues } from 'kea'

import { inboxReportDetailLogic } from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import type { SignalReport } from 'products/signals/frontend/inbox/types'

import { researchNotes } from './todayFigureSources'
import { TodayReportBody } from './TodayReportBody'

export function TodayReportLiveBody({ report }: { report: SignalReport }): JSX.Element {
    const { implementationSlotClaim, reportTaskToOpen, reportArtefacts } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    return (
        <TodayReportBody
            report={report}
            live={{
                reportTaskToOpen,
                implementationSlotClaim,
                research: researchNotes(reportArtefacts),
            }}
        />
    )
}
