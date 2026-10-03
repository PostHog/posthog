import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconExternal, IconHide } from '@posthog/icons'
import { Badge, Button, Skeleton } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ReportChart } from 'products/signals/frontend/inbox/components/detail/ReportChart'
import { ReportChartsContext } from 'products/signals/frontend/inbox/components/detail/reportChartsContext'
import { ReportSummaryBody } from 'products/signals/frontend/inbox/components/detail/ReportSummaryBody'
import { canResolveReport, hasOpenImplementationPr } from 'products/signals/frontend/inbox/utils/reportActions'

import { itemStateLabel } from './todayBriefingItems'
import { TodayIcon } from './TodayIcon'
import { TodayReportActionButton } from './TodayReportActionButton'
import { TodayReportVerdict, todayLogic } from './todayLogic'
import { TodayReportEvidence } from './TodayReportEvidence'
import { todayReportLogic } from './todayReportLogic'
import { TodayReportPrompts } from './TodayReportPrompts'
import { TodaySampleBanner } from './TodaySampleBanner'
import { isSampleReportId } from './todaySampleReports'
import { reportIcon, reportMeta, reportSource, reportTitle } from './todaySignalReports'

export function TodayReportPage({ reportId }: { reportId: string }): JSX.Element {
    const logic = todayReportLogic({ reportId })
    const { currentReport, reportFailed, fullReportLoading, chartPlacements, chartsById, trailingCharts, reportState } =
        useValues(logic)
    const { loadFullReport } = useActions(logic)
    const { requestReportVerdict } = useActions(todayLogic)
    const sampleDisabledReason = isSampleReportId(reportId) ? 'This is a sample report.' : undefined

    if (!currentReport) {
        return reportFailed ? (
            <div className="TodayReport Today__page">
                <TodaySampleBanner />
                <h1 className="TodayReport__heading">Couldn’t open this report.</h1>
                <div className="TodayReport__body">
                    <p>It may have been deleted, or the request failed. Try again, or go back to today’s briefing.</p>
                </div>
                <div className="flex flex-wrap gap-2 mt-6" data-quill>
                    <Button
                        variant="primary"
                        onClick={() => loadFullReport()}
                        loading={fullReportLoading}
                        data-attr="today-report-retry"
                    >
                        Try again
                    </Button>
                    <Button
                        variant="outline"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.projectHomepage()} />}
                        data-attr="today-report-missing-home"
                    >
                        Back to Home
                    </Button>
                </div>
            </div>
        ) : (
            <div className="TodayReport Today__page flex flex-col gap-4" data-quill>
                <Skeleton className="h-4 w-48" />
                <Skeleton className="h-10 w-3/4" />
                <Skeleton className="h-24" />
            </div>
        )
    }

    const stateLabel = itemStateLabel({ state: reportState })
    const giveVerdict = (verdict: TodayReportVerdict): void =>
        requestReportVerdict(
            {
                reportId: currentReport.id,
                title: reportTitle(currentReport),
                hasOpenPullRequest: hasOpenImplementationPr(currentReport),
            },
            verdict,
            'report_page'
        )

    return (
        <div
            className="TodayReport Today__page"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--report-color': reportSource(currentReport).color } as React.CSSProperties}
        >
            <TodaySampleBanner />
            <article>
                <div className="TodayReport__kicker">
                    <span className="TodayTile">
                        <TodayIcon icon={reportIcon(currentReport)} />
                    </span>
                    <span>{reportMeta(currentReport)}</span>
                    {(currentReport.priority || stateLabel) && (
                        <span className="flex gap-1" data-quill>
                            {currentReport.priority && <Badge>{currentReport.priority}</Badge>}
                            {stateLabel && (
                                <Badge variant={reportState === 'done' ? 'completed' : 'default'}>{stateLabel}</Badge>
                            )}
                        </span>
                    )}
                </div>
                <h1 className="TodayReport__heading">{reportTitle(currentReport)}</h1>
                <div className="flex flex-wrap gap-2 mt-4" data-quill>
                    {currentReport.implementation_pr_url && (
                        <TodayReportActionButton
                            variant="primary"
                            to={currentReport.implementation_pr_url}
                            targetBlank
                            disabledReason={sampleDisabledReason}
                            dataAttr="today-report-pull-request"
                        >
                            Review the pull request
                            <IconExternal />
                        </TodayReportActionButton>
                    )}
                    <TodayReportActionButton
                        to={urls.inboxReport('reports', currentReport.id)}
                        disabledReason={sampleDisabledReason}
                        dataAttr="today-report-open-inbox"
                    >
                        Open in Inbox
                    </TodayReportActionButton>
                    {!stateLabel && (
                        <>
                            <TodayReportActionButton
                                onClick={() => giveVerdict('resolve')}
                                disabledReason={
                                    sampleDisabledReason ??
                                    (canResolveReport(currentReport)
                                        ? undefined
                                        : 'You can resolve a report only after the agent finishes its research.')
                                }
                                dataAttr="today-report-resolve"
                            >
                                <IconCheckCircle />
                                Resolve
                            </TodayReportActionButton>
                            <TodayReportActionButton
                                onClick={() => giveVerdict('dismiss')}
                                disabledReason={sampleDisabledReason}
                                dataAttr="today-report-dismiss"
                            >
                                <IconHide />
                                Dismiss
                            </TodayReportActionButton>
                        </>
                    )}
                </div>
                <ReportChartsContext.Provider value={chartsById}>
                    <div className="TodayReport__body">
                        {currentReport.summary ? (
                            <ReportSummaryBody summary={currentReport.summary} chartPlacements={chartPlacements} />
                        ) : (
                            <p>No summary yet. An agent is still investigating.</p>
                        )}
                        {trailingCharts.map((chart) => (
                            <ReportChart key={chart.chart_id} chartId={chart.chart_id} />
                        ))}
                    </div>
                </ReportChartsContext.Provider>
            </article>
            <TodayReportEvidence reportId={currentReport.id} />
            <TodayReportPrompts report={currentReport} />
        </div>
    )
}
