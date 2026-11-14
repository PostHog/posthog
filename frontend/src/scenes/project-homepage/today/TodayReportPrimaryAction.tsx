import { useActions } from 'kea'

import { IconClock, IconPullRequest } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { type InboxReportActionSurface, captureInboxReportAction } from 'products/signals/frontend/inbox/inboxAnalytics'
import { inboxTaskKickoffLogic } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayImplementMenu } from './TodayImplementMenu'
import { TodayPrimaryAction } from './todayNextStep'
import { SAMPLE_REPORT_REASON } from './todaySampleReports'

export function TodayReportPrimaryAction({
    primary,
    report,
    reportUrl,
    isSample,
    startReason,
    surface,
}: {
    primary: TodayPrimaryAction
    report: SignalReport
    reportUrl: string
    isSample: boolean
    startReason: string | null
    surface: InboxReportActionSurface
}): JSX.Element {
    const { openReportTask } = useActions(inboxTaskKickoffLogic)
    if (primary.kind === 'review') {
        return (
            <Button
                variant="primary"
                className="me-1"
                render={<LinkPrimitive to={primary.url} target="_blank" />}
                onClick={() => captureInboxReportAction({ report, actionType: 'open_pr', surface })}
                disabledReason={isSample ? SAMPLE_REPORT_REASON : null}
                data-attr="today-report-review-pr"
            >
                <IconPullRequest />
                <span>{primary.label}</span>
            </Button>
        )
    }
    if (primary.kind === 'open_task') {
        return (
            <Button
                variant="primary"
                className="me-1"
                onClick={() => openReportTask(report, primary.taskId, primary.runId)}
                data-attr="today-report-open-task"
            >
                <IconClock />
                <span>{primary.label}</span>
            </Button>
        )
    }
    return (
        <TodayImplementMenu
            report={report}
            reportUrl={reportUrl}
            disabledReason={isSample ? SAMPLE_REPORT_REASON : null}
            postHogDisabledReason={startReason}
            surface={surface}
        />
    )
}
