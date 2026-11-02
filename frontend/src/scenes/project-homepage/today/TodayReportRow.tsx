import { useActions, useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import { hasOpenImplementationPr } from 'products/signals/frontend/inbox/utils/reportActions'

import { todayLogic, type TodayReportOpenSource } from './todayLogic'
import { priorityTone } from './todayPriority'
import { TodayReportRowDetail } from './TodayReportRowDetail'
import { reportStateLabel } from './todayReportState'
import { TodayRow } from './TodayRow'
import { pullRequestFact, rowFacts } from './todayRowFacts'
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
            facts={rowFacts(
                state
                    ? [reportStateLabel(state)]
                    : [
                          pullRequestFact(
                              report.implementation_pr_merged
                                  ? 'merged'
                                  : (report.implementation_pr_state ?? (report.implementation_pr_url ? 'open' : null))
                          ),
                          `Updated ${dayjs(report.updated_at).fromNow()}`,
                      ]
            )}
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
