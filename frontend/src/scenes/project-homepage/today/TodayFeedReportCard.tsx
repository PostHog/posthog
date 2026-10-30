import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import { hasOpenImplementationPr } from 'products/signals/frontend/inbox/utils/reportActions'

import { TodayFeedCard, type TodayFeedCardTracking } from './TodayFeedCard'
import { feedReportFacts } from './todayFeedReport'
import { TodayFeedReportChips } from './TodayFeedReportChips'
import { todayLogic, type TodayReportOpenSource } from './todayLogic'
import { priorityTone } from './todayPriority'
import { reportStateLabel } from './todayReportState'
import { reportIcon } from './todayRowIcons'
import { reportSourceLine, reportTitle } from './todaySignalReports'
import { TodayVerdictButtons } from './TodayVerdictButtons'
import { todayVerdictLogic } from './todayVerdictLogic'

export function TodayFeedReportCard({
    report,
    source,
    done,
    tracking,
}: {
    report: SignalReport
    source: TodayReportOpenSource
    done: boolean
    tracking: TodayFeedCardTracking
}): JSX.Element {
    const { reportPreviews } = useValues(todayLogic)
    const { reportStateOverrides } = useValues(todayVerdictLogic)
    const { reportOpened, askAi } = useActions(todayLogic)
    const title = reportTitle(report)
    const state = reportStateOverrides[report.id]
    const preview = reportPreviews[report.id]
    const { figure, series, pullRequest, prompt } = feedReportFacts(report, title, preview, done)
    return (
        <TodayFeedCard
            icon={reportIcon(report)}
            source={reportSourceLine(report).line}
            title={title}
            tone={priorityTone(report.priority)}
            priority={report.priority}
            meta={state ? reportStateLabel(state) : <TZLabel time={report.updated_at} noStyles />}
            lead={preview?.lead}
            figure={figure}
            series={series}
            chips={
                (pullRequest || prompt) && (
                    <TodayFeedReportChips
                        pullRequest={pullRequest}
                        prompt={prompt}
                        onAsk={(question) => askAi(question, 'feed', report)}
                    />
                )
            }
            secondaryActions={
                done ? null : (
                    <TodayVerdictButtons
                        target={{ reportId: report.id, title, hasOpenPullRequest: hasOpenImplementationPr(report) }}
                        labelled
                    />
                )
            }
            open={{
                to: urls.todayReport(report.id),
                label: 'Open report',
                onOpen: () => reportOpened(report, source),
                crossfade: true,
            }}
            done={done}
            tracking={tracking}
            reportId={report.id}
            dataAttr="today-feed-report"
        />
    )
}
