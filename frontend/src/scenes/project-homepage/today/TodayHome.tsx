import './Today.scss'

import { useValues } from 'kea'
import { Suspense } from 'react'

import { Skeleton } from '@posthog/quill'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { TodayPreviewCardProvider } from '~/layout/today/TodayPreviewCardProvider'

import { TodayBriefing } from './TodayBriefing'
import { todayLogic } from './todayLogic'

const TodayReportPage = lazyWithRetry(() => import('./TodayReportPage').then((m) => ({ default: m.TodayReportPage })))

/** The Today homepage: the daily briefing at `/home`, or one report at `/home/reports/:reportId`. */
export function TodayHome(): JSX.Element {
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
                <TodayPreviewCardProvider>
                    <TodayBriefing />
                </TodayPreviewCardProvider>
            )}
        </div>
    )
}
