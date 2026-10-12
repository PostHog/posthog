import { useActions, useValues } from 'kea'

import { Button, Heading, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodayReportBody } from './TodayReportBody'
import { TodayReportLiveBody } from './TodayReportLiveBody'
import { todayReportLogic } from './todayReportLogic'
import { TodaySampleBanner } from './TodaySampleBanner'

function ReportFailed({ reportId }: { reportId: string }): JSX.Element {
    const logic = todayReportLogic({ reportId })
    const { fullReportLoading, pageLoading } = useValues(logic)
    const { loadFullReport, loadPage } = useActions(logic)
    return (
        <div className="flex max-w-150 flex-col gap-3">
            <Heading size="lg" render={<h1 />}>
                Couldn’t open this report.
            </Heading>
            <Text variant="muted" render={<p />}>
                It may have been deleted, or the request failed. Try again, or go back to today’s briefing.
            </Text>
            <div className="mt-3 flex flex-wrap gap-2">
                <Button
                    variant="primary"
                    onClick={() => {
                        loadFullReport()
                        loadPage()
                    }}
                    loading={fullReportLoading || pageLoading}
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
    )
}

function ReportSkeleton(): JSX.Element {
    return (
        <div className="flex max-w-150 flex-col gap-10" aria-busy>
            <div className="flex flex-col gap-3">
                <div className="flex h-7 items-center justify-between">
                    <Skeleton className="h-3 w-48" />
                    <Skeleton className="h-3 w-40" />
                </div>
                <Skeleton className="h-6 w-4/5" />
                <div className="flex flex-col gap-2 pt-1">
                    <Skeleton className="h-3.5 w-full" />
                    <Skeleton className="h-3.5 w-2/3" />
                </div>
                <Skeleton className="mt-3 h-3.5 w-3/5" />
            </div>
            <div className="flex flex-col gap-2">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-3.5 w-full" />
                <Skeleton className="h-3.5 w-1/2" />
                <div className="mt-2 flex items-center gap-4">
                    <Skeleton className="h-8 w-32" />
                    <Skeleton className="h-3.5 w-16" />
                    <Skeleton className="h-3.5 w-24" />
                </div>
            </div>
            <div className="flex flex-col gap-5">
                <Skeleton className="h-4 w-20" />
                {['w-11/12', 'w-3/4', 'w-5/6'].map((width) => (
                    <div key={width} className="flex items-start justify-between gap-6">
                        <div className="flex flex-1 flex-col gap-2">
                            <Skeleton className="h-3.5 w-full" />
                            <Skeleton className={`h-3.5 ${width}`} />
                        </div>
                        <Skeleton className="h-3 w-12" />
                    </div>
                ))}
            </div>
        </div>
    )
}

export function TodayReportPage({ reportId }: { reportId: string }): JSX.Element {
    const { currentReport, page, reportFailed, isSample } = useValues(todayReportLogic({ reportId }))

    if ((!currentReport || !page) && !reportFailed) {
        return (
            <div className="TodayReport Today__page" data-quill>
                <ReportSkeleton />
            </div>
        )
    }

    return (
        <div className="TodayReport Today__page" data-quill>
            <TodaySampleBanner />
            {reportFailed && <ReportFailed reportId={reportId} />}
            {currentReport && isSample && <TodayReportBody report={currentReport} live={null} />}
            {currentReport && !isSample && <TodayReportLiveBody report={currentReport} />}
        </div>
    )
}
