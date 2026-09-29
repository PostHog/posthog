import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ReportChart } from 'products/signals/frontend/inbox/components/detail/ReportChart'
import { ReportSummaryBody } from 'products/signals/frontend/inbox/components/detail/ReportSummaryBody'

import { TodayIcon } from './TodayIcon'
import { TodayReportEvidence } from './TodayReportEvidence'
import { todayReportLogic } from './todayReportLogic'
import { TodayReportPrompts } from './TodayReportPrompts'
import { reportIcon, reportMeta, reportSource, reportTitle } from './todaySignalReports'

export function TodayReportPage({ reportId }: { reportId: string }): JSX.Element {
    const logic = todayReportLogic({ reportId })
    const { currentReport, reportFailed, fullReportLoading, chartPlacements, trailingCharts, reportUrl } =
        useValues(logic)
    const { loadFullReport } = useActions(logic)

    if (!currentReport) {
        return reportFailed ? (
            <div className="TodayReport Today__page">
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

    return (
        <div
            className="TodayReport Today__page"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--report-color': reportSource(currentReport).color } as React.CSSProperties}
        >
            <article>
                <div className="TodayReport__kicker">
                    <span className="TodayTile">
                        <TodayIcon icon={reportIcon(currentReport)} />
                    </span>
                    <span>{reportMeta(currentReport)}</span>
                    {currentReport.priority && <LemonTag type="muted">{currentReport.priority}</LemonTag>}
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
                            data-attr="today-report-pull-request"
                        >
                            Review the pull request
                        </LemonButton>
                    )}
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.inboxReport('reports', currentReport.id)}
                        data-attr="today-report-open-inbox"
                    >
                        Open in Inbox
                    </LemonButton>
                </div>
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
            </article>
            <TodayReportEvidence reportId={currentReport.id} />
            <TodayReportPrompts report={currentReport} reportUrl={reportUrl} />
        </div>
    )
}
