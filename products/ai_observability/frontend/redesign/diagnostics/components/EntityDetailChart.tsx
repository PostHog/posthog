import { LemonSkeleton } from '@posthog/lemon-ui'

import { ListEmptyState } from '../../lists/components/ListEmptyState'
import { ListErrorState } from '../../lists/components/ListErrorState'
import type { DetailLoad } from '../diagnosticsDrawerReads'
import { EntityTrendChart } from './EntityTrendChart'

interface EntityDetailSeries {
    item: { series: number[] }
    previousSeries: number[]
    bucketStarts: string[]
}

export interface EntityDetailChartProps {
    detail: DetailLoad<EntityDetailSeries>
    timezone: string
    /** What the chart's place says when the entity has nothing in the date range. */
    notFound: { title: string; description: string }
    failedTitle: string
    onRetry: () => void
    'data-attr': string
}

export function EntityDetailChart({
    detail,
    timezone,
    notFound,
    failedTitle,
    onRetry,
    'data-attr': dataAttr,
}: EntityDetailChartProps): JSX.Element {
    switch (detail.status) {
        case 'ready':
            return (
                <div className="rounded border p-3">
                    <EntityTrendChart
                        series={detail.value.item.series}
                        previousSeries={detail.value.previousSeries}
                        bucketStarts={detail.value.bucketStarts}
                        timezone={timezone}
                    />
                </div>
            )
        case 'not_found':
            return <ListEmptyState title={notFound.title} description={notFound.description} />
        case 'error':
            return (
                <ListErrorState
                    title={failedTitle}
                    description="Try again. If it keeps happening, contact support."
                    retry={{ onClick: onRetry, 'data-attr': `${dataAttr}-retry` }}
                />
            )
        default:
            return <LemonSkeleton className="h-54" />
    }
}
