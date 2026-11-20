import { useActions, useValues } from 'kea'

import { hasOpenImplementationPr } from '@posthog/agent-contracts/signal-report-state'

import { urls } from 'scenes/urls'

import { SignalReport } from 'products/signals/frontend/inbox/types'

import { todayLogic, type TodayReportOpenSource } from './todayLogic'
import { priorityTone } from './todayPriority'
import { TodayReportRowDetail } from './TodayReportRowDetail'
import { TodayRow } from './TodayRow'
import { reportRowFacts } from './todayRowFacts'
import { reportIcon } from './todayRowIcons'
import { reportTitle } from './todaySignalReports'
import { TodayVerdictButtons } from './TodayVerdictButtons'
import { type TodayReportVerdictTarget, todayVerdictLogic } from './todayVerdictLogic'

export function TodayReportRow({
    report,
    source,
    done,
}: {
    report: SignalReport
    source: TodayReportOpenSource
    done: boolean
}): JSX.Element {
    const { reportPreviews, expandedReportRows } = useValues(todayLogic)
    const { reportStateOverrides } = useValues(todayVerdictLogic)
    const { reportOpened, toggleReportRow } = useActions(todayLogic)
    const state = reportStateOverrides[report.id]
    const preview = reportPreviews[report.id]
    const { facts, reason } = reportRowFacts(report, state)
    const to = urls.todayReport(report.id)
    const target: TodayReportVerdictTarget = {
        reportId: report.id,
        title: reportTitle(report),
        hasOpenPullRequest: hasOpenImplementationPr(report),
    }
    return (
        <TodayRow
            tone={priorityTone(report.priority)}
            icon={reportIcon(report)}
            title={target.title}
            label={report.priority ?? undefined}
            facts={facts}
            reason={reason}
            to={to}
            onOpen={() => reportOpened(report, source)}
            expansion={
                preview
                    ? {
                          expanded: !!expandedReportRows[report.id],
                          onToggle: () => toggleReportRow(report.id, report.id),
                          detail: (
                              <TodayReportRowDetail
                                  preview={preview}
                                  reason={report.personal_reason}
                                  to={to}
                                  onOpen={() => reportOpened(report, source)}
                                  actions={done ? null : <TodayVerdictButtons target={target} labelled />}
                                  dataAttr="today-list-report"
                              />
                          ),
                      }
                    : undefined
            }
            actions={<TodayVerdictButtons target={target} />}
            done={done}
            reportId={report.id}
            dataAttr="today-list-report"
        />
    )
}
