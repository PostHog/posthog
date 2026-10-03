import { useValues } from 'kea'
import { ComponentProps } from 'react'

import { inboxReportDetailLogic } from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'

import { TodayReportBody } from './TodayReportBody'
import { researchNotes } from './todayReportPresentation'

export function TodayReportLiveBody(props: Omit<ComponentProps<typeof TodayReportBody>, 'live'>): JSX.Element {
    const { implementationSlotClaim, reportTaskToOpen, reportArtefacts } = useValues(
        inboxReportDetailLogic({ reportId: props.report.id, report: props.report })
    )
    return (
        <TodayReportBody
            {...props}
            live={{
                reportTaskToOpen,
                implementationSlotClaim,
                research: researchNotes(reportArtefacts),
            }}
        />
    )
}
