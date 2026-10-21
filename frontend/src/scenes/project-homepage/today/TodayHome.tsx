import './Today.scss'

import { useMountedLogic, useValues } from 'kea'
import { Suspense } from 'react'

import { Skeleton } from '@posthog/quill'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { TodayHomePage } from './TodayHomePage'
import { todayLogic } from './todayLogic'
import { todayReportQueueLogic } from './todayReportQueueLogic'

const TodayReportPage = lazyWithRetry(() => import('./TodayReportPage').then((m) => ({ default: m.TodayReportPage })))

/** The Today homepage at `/home`, or one report at `/home/reports/:reportId`. */
export function TodayHome(): JSX.Element {
    useMountedLogic(todayReportQueueLogic)
    const { reportId } = useValues(todayLogic)

    return (
        <div className="Today flex-1 min-h-full @container/today">
            {reportId ? (
                <Suspense
                    fallback={
                        <div className="TodayReport Today__page flex flex-col gap-4">
                            <Skeleton className="h-4 w-48" />
                            <Skeleton className="h-10 w-3/4" />
                            <Skeleton className="h-24" />
                        </div>
                    }
                >
                    <TodayReportPage key={reportId} reportId={reportId} />
                </Suspense>
            ) : (
                <TodayHomePage />
            )}
        </div>
    )
}
