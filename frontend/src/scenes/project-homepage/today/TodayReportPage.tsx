import { useActions, useValues } from 'kea'

import { Button, Heading, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ReportChartsContext } from 'products/signals/frontend/inbox/components/detail/reportChartsContext'
import { ReportFeedbackFooter } from 'products/signals/frontend/inbox/components/detail/ReportFeedbackFooter'

import { TodayReportContinue } from './TodayReportContinue'
import { TodayReportEvidence } from './TodayReportEvidence'
import { TodayReportHeader } from './TodayReportHeader'
import { TodayReportImpact } from './TodayReportImpact'
import { TodayReportLiveContinue } from './TodayReportLiveContinue'
import { todayReportLogic } from './todayReportLogic'
import { TodayReportPrompts } from './TodayReportPrompts'
import { TodayReportProposal } from './TodayReportProposal'
import { TodaySampleBanner } from './TodaySampleBanner'
import { isSampleReportId } from './todaySampleReports'

export function TodayReportPage({ reportId }: { reportId: string }): JSX.Element {
    const logic = todayReportLogic({ reportId })
    const { currentReport, reportFailed, fullReportLoading, chartsById, reportUrl, sections, reportState } =
        useValues(logic)
    const { loadFullReport } = useActions(logic)

    if (!currentReport) {
        return reportFailed ? (
            <div className="TodayReport Today__page" data-quill>
                <TodaySampleBanner />
                <div className="flex max-w-170 flex-col gap-3">
                    <Heading size="lg" render={<h1 />}>
                        Couldn’t open this report.
                    </Heading>
                    <Text variant="muted" render={<p />}>
                        It may have been deleted, or the request failed. Try again, or go back to today’s briefing.
                    </Text>
                    <div className="mt-3 flex flex-wrap gap-2">
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
                            render={<LinkPrimitive to={urls.projectHomepage()} />}
                            data-attr="today-report-missing-home"
                        >
                            Back to Home
                        </Button>
                    </div>
                </div>
            </div>
        ) : (
            <div className="TodayReport Today__page" data-quill>
                <div className="flex max-w-170 flex-col gap-4">
                    <Skeleton className="h-4 w-48" />
                    <Skeleton className="h-7 w-3/4" />
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-24 w-full" />
                </div>
            </div>
        )
    }

    const isSample = isSampleReportId(currentReport.id)

    return (
        <div className="TodayReport Today__page" data-quill>
            <TodaySampleBanner />
            <article className="flex max-w-170 flex-col gap-8">
                <div className="flex flex-col gap-5">
                    <TodayReportHeader report={currentReport} reportState={reportState} />
                    <ReportChartsContext.Provider value={chartsById}>
                        <TodayReportImpact report={currentReport} sections={sections} />
                    </ReportChartsContext.Provider>
                </div>
                <TodayReportProposal sections={sections} />
                {isSample ? (
                    <TodayReportContinue
                        report={currentReport}
                        reportUrl={reportUrl}
                        reportTaskToOpen={null}
                        implementationSlotClaim={null}
                    />
                ) : (
                    <TodayReportLiveContinue report={currentReport} reportUrl={reportUrl} />
                )}
                <TodayReportEvidence reportId={currentReport.id} />
                <TodayReportPrompts report={currentReport} />
                {!isSample && <ReportFeedbackFooter report={currentReport} />}
            </article>
        </div>
    )
}
