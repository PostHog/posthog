import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconExternal, IconHide } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ReportChart } from 'products/signals/frontend/inbox/components/detail/ReportChart'
import { ReportChartsContext } from 'products/signals/frontend/inbox/components/detail/reportChartsContext'
import { ReportSummaryBody } from 'products/signals/frontend/inbox/components/detail/ReportSummaryBody'
import { canResolveReport, hasOpenImplementationPr } from 'products/signals/frontend/inbox/utils/reportActions'

import { itemStateLabel } from './todayBriefingItems'
import { TodayIcon } from './TodayIcon'
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
                <div className="flex flex-wrap gap-2 mt-6">
                    <LemonButton
                        type="primary"
                        onClick={() => loadFullReport()}
                        loading={fullReportLoading}
                        data-attr="today-report-retry"
                    >
                        Try again
                    </LemonButton>
                    <LemonButton type="secondary" to={urls.projectHomepage()} data-attr="today-report-missing-home">
                        Back to Home
                    </LemonButton>
                </div>
            </div>
        ) : (
            <div className="TodayReport Today__page flex flex-col gap-4">
                <LemonSkeleton className="h-4 w-48" />
                <LemonSkeleton className="h-10 w-3/4" />
                <LemonSkeleton className="h-24" />
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
                    {currentReport.priority && <LemonTag type="muted">{currentReport.priority}</LemonTag>}
                    {stateLabel && (
                        <LemonTag type={reportState === 'done' ? 'success' : 'muted'}>{stateLabel}</LemonTag>
                    )}
                </div>
                <h1 className="TodayReport__heading">{reportTitle(currentReport)}</h1>
                <div className="flex flex-wrap gap-2 mt-4">
                    {currentReport.implementation_pr_url && (
                        <LemonButton
                            type="primary"
                            size="small"
                            to={currentReport.implementation_pr_url}
                            targetBlank
                            sideIcon={<IconExternal />}
                            disabledReason={sampleDisabledReason}
                            data-attr="today-report-pull-request"
                        >
                            Review the pull request
                        </LemonButton>
                    )}
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.inboxReport('reports', currentReport.id)}
                        disabledReason={sampleDisabledReason}
                        data-attr="today-report-open-inbox"
                    >
                        Open in Inbox
                    </LemonButton>
                    {!stateLabel && (
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconCheckCircle />}
                                onClick={() => giveVerdict('resolve')}
                                disabledReason={
                                    sampleDisabledReason ??
                                    (canResolveReport(currentReport)
                                        ? undefined
                                        : 'You can resolve a report only after the agent finishes its research.')
                                }
                                data-attr="today-report-resolve"
                            >
                                Resolve
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconHide />}
                                onClick={() => giveVerdict('dismiss')}
                                disabledReason={sampleDisabledReason}
                                data-attr="today-report-dismiss"
                            >
                                Dismiss
                            </LemonButton>
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
