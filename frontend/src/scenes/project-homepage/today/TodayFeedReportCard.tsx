import { useActions, useValues } from 'kea'

import { IconPullRequest, IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import { hasOpenImplementationPr } from 'products/signals/frontend/inbox/utils/reportActions'
import {
    formatReportMetricValue,
    selectReportCardImpactMetric,
} from 'products/signals/frontend/inbox/utils/reportMetrics'

import { TodayFeedCard, type TodayFeedCardTracking } from './TodayFeedCard'
import { todayLogic, type TodayReportOpenSource } from './todayLogic'
import { priorityTone } from './todayPriority'
import { reportStateLabel } from './todayReportState'
import { pullRequestFact } from './todayRowFacts'
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
    const metric = selectReportCardImpactMetric(report.metrics)
    const metricValue = metric ? formatReportMetricValue(metric, metric.value) : null
    const pullRequest = preview?.pullRequest
    const pullRequestNumber = pullRequest?.url.match(/\/pull\/(\d+)/)?.[1]
    // A title such as "Review PR #9123" already names the pull request.
    const showPullRequest = pullRequest && !title.includes(`#${pullRequestNumber}`)
    const prompt = done ? undefined : report.suggested_prompts?.[0]
    return (
        <TodayFeedCard
            icon={reportIcon(report)}
            source={reportSourceLine(report).line}
            title={title}
            tone={priorityTone(report.priority)}
            priority={report.priority}
            meta={state ? reportStateLabel(state) : dayjs(report.updated_at).fromNow()}
            lead={preview?.lead}
            figure={metric && metricValue ? { value: metricValue, label: metric.title } : null}
            series={metric?.series}
            chips={
                (showPullRequest || prompt) && (
                    <>
                        {showPullRequest && (
                            <Button
                                variant="outline"
                                size="sm"
                                nativeButton={false}
                                render={<LinkPrimitive to={pullRequest.url} target="_blank" />}
                                data-attr="today-feed-report-pr"
                            >
                                <IconPullRequest />
                                {pullRequestFact(pullRequest.state ?? 'open')}
                                {pullRequestNumber && <span translate="no">#{pullRequestNumber}</span>}
                            </Button>
                        )}
                        {prompt && (
                            <Button
                                variant="outline"
                                size="sm"
                                className="min-w-0"
                                onClick={() => askAi(prompt, 'feed', report)}
                                data-attr="today-feed-report-ask"
                            >
                                <IconSparkles />
                                <span className="truncate">{prompt}</span>
                            </Button>
                        )}
                    </>
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
            dataAttr="today-feed-report"
        />
    )
}
