export interface RunBucket {
    /** The bucket start, as the API keys it: an ISO date, or an ISO hour for a one day window. */
    key: string
    successful: number
    failed: number
    /** Extra words for the bar's tooltip, such as how the counts split between kinds of run. */
    note?: string
}

/**
 * Stacked success and failure bars, one per bucket of the window. `compact` is a tiny strip for a stat tile.
 * `large` is a taller chart with the first and last bucket named underneath.
 */
export function WarehouseRunBars({
    buckets,
    unit,
    size = 'compact',
    'data-attr': dataAttr,
}: {
    buckets: RunBucket[]
    unit: 'day' | 'hour'
    size?: 'compact' | 'large'
    'data-attr'?: string
}): JSX.Element {
    const peak = Math.max(1, ...buckets.map((bucket) => bucket.successful + bucket.failed))
    const succeeded = buckets.reduce((sum, bucket) => sum + bucket.successful, 0)
    const failed = buckets.reduce((sum, bucket) => sum + bucket.failed, 0)
    const large = size === 'large'

    return (
        <div className="flex flex-col gap-1" data-attr={dataAttr}>
            <div
                role="img"
                aria-label={`Runs per ${unit}: ${succeeded} succeeded, ${failed} failed`}
                className={large ? 'flex h-28 items-end gap-0.5' : 'flex h-6 items-end gap-px'}
            >
                {buckets.map((bucket) => (
                    <div
                        key={bucket.key}
                        title={`${bucket.key.replace('T', ' ')}${unit === 'hour' ? ':00' : ''}: ${bucket.successful} succeeded, ${bucket.failed} failed${bucket.note ? ` (${bucket.note})` : ''}`}
                        className="flex h-full min-w-px flex-1 flex-col justify-end"
                    >
                        {bucket.failed > 0 ? (
                            <div
                                className="w-full bg-[var(--destructive-foreground)]"
                                style={{ height: `${(bucket.failed / peak) * 100}%`, minHeight: 2 }}
                            />
                        ) : null}
                        {bucket.successful > 0 ? (
                            <div
                                className="w-full bg-[var(--success-foreground)]"
                                style={{ height: `${(bucket.successful / peak) * 100}%`, minHeight: 2 }}
                            />
                        ) : (
                            <div className="h-px w-full bg-[var(--input)]" />
                        )}
                    </div>
                ))}
            </div>
            {large && buckets.length > 0 ? (
                <div className="flex justify-between text-xs tabular-nums text-muted-foreground" aria-hidden>
                    <span>{buckets[0].key}</span>
                    <span>{buckets[buckets.length - 1].key}</span>
                </div>
            ) : null}
        </div>
    )
}
