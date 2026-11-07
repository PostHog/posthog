import { Suspense, lazy } from 'react'

import { Skeleton } from '@posthog/quill'

import { retryImport } from 'lib/utils/retryImport'

import type { TodayTone } from './todayTone'

const TodaySparkline = lazy(() =>
    retryImport(() => import('./TodaySparkline').then((m) => ({ default: m.TodaySparkline })))
)

export function TodayNewsChart({
    values,
    labels,
    tone,
    emphasizeLast,
    className,
}: {
    values: number[]
    labels: string[]
    tone: TodayTone
    emphasizeLast: number
    className: string
}): JSX.Element {
    return (
        <span className={className}>
            <Suspense fallback={<Skeleton className="h-full w-full" />}>
                <TodaySparkline values={values} labels={labels} tone={tone} emphasizeLast={emphasizeLast} fromZero />
            </Suspense>
        </span>
    )
}
