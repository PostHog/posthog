import { useValues } from 'kea'

import { Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import type { BucketStatusEnumApi } from '../../generated/api.schemas'
import { compactHeadline, describeBucket, formatBucket, formatBucketShort } from './evaluationOverviewDisplay'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

/** Below this many graded results the backend never marks a bucket unusual, so the cell is greyed as unreliable. */
const LOW_EVIDENCE_BUCKET_VOLUME = 30

const STATUS_CLASSES: Record<BucketStatusEnumApi, string> = {
    dip: 'bg-warning border-transparent',
    normal: 'bg-muted opacity-40 border-transparent',
    none: 'border-dashed border-primary',
}

const STATUS_LABELS: Record<BucketStatusEnumApi, string> = {
    dip: 'Unusual compared with the previous period',
    normal: 'In line with the previous period',
    none: 'No graded results',
}

const LOW_EVIDENCE_CLASSES = 'bg-muted opacity-15 border-transparent'

const LEGEND_ORDER: BucketStatusEnumApi[] = ['dip', 'normal', 'none']

export function EvaluationStatusGrid(): JSX.Element {
    const { statusGridRows, buckets, interval } = useValues(evaluationsOverviewLogic)

    return (
        <div className="flex flex-col gap-1 text-sm">
            <div className="flex items-center gap-3 text-xs text-secondary">
                <span className="w-28 @2xl:w-48 shrink-0" />
                <span className="flex-1 flex justify-between">
                    <span>{buckets.length ? formatBucketShort(buckets[0], interval) : ''}</span>
                    <span>{buckets.length ? formatBucketShort(buckets[buckets.length - 1], interval) : ''}</span>
                </span>
                <span className="w-24 @2xl:w-28 shrink-0 text-right">Result</span>
            </div>
            {statusGridRows.map((row) => (
                <div key={row.id} className={cn('flex items-center gap-3', row.lowEvidence && 'opacity-60')}>
                    <Link
                        to={urls.aiObservabilityEvaluation(row.id)}
                        subtle
                        className="w-28 @2xl:w-48 shrink-0 truncate text-primary"
                        data-attr="evaluation-overview-status-grid-name"
                    >
                        {row.name}
                    </Link>
                    <span className="flex-1 min-w-0 flex gap-0.5">
                        {row.bucketStatus.map((status, index) => {
                            const volume = row.trend.volume[index] ?? 0
                            const lowEvidence = status === 'normal' && volume < LOW_EVIDENCE_BUCKET_VOLUME
                            return (
                                <Tooltip
                                    key={buckets[index] ?? index}
                                    delayMs={0}
                                    title={
                                        <>
                                            <div className="font-semibold">{`${row.name}, ${formatBucket(buckets[index], interval)}`}</div>
                                            <div>{describeBucket(row, index)}</div>
                                            <div>
                                                {lowEvidence ? 'Too few results to compare' : STATUS_LABELS[status]}
                                            </div>
                                        </>
                                    }
                                >
                                    <span
                                        aria-label={`${row.name}, ${formatBucket(buckets[index], interval)}: ${STATUS_LABELS[status]}`}
                                        className={cn(
                                            'h-5 flex-1 min-w-0 rounded-sm border',
                                            lowEvidence ? LOW_EVIDENCE_CLASSES : STATUS_CLASSES[status]
                                        )}
                                    />
                                </Tooltip>
                            )
                        })}
                    </span>
                    <span className="w-24 @2xl:w-28 shrink-0 text-right tabular-nums truncate font-semibold">
                        {row.gradedCount === 0 ? (row.enabled ? 'No results' : 'Disabled') : compactHeadline(row)}
                    </span>
                </div>
            ))}
            <div className="flex flex-wrap gap-x-4 gap-y-1 pt-2 text-xs text-secondary">
                {LEGEND_ORDER.map((status) => (
                    <span key={status} className="inline-flex items-center gap-1.5">
                        <span className={cn('inline-block size-3 rounded-sm border', STATUS_CLASSES[status])} />
                        <span>{STATUS_LABELS[status]}</span>
                    </span>
                ))}
                <span className="inline-flex items-center gap-1.5">
                    <span className={cn('inline-block size-3 rounded-sm border', LOW_EVIDENCE_CLASSES)} />
                    <span>Too few results to compare</span>
                </span>
            </div>
        </div>
    )
}
