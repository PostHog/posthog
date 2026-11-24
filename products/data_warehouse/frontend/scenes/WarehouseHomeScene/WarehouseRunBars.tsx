import type { RunBucket } from './warehouseHomeStats'

/** A tiny strip of stacked success and failure bars, one per bucket of the window. */
export function WarehouseRunBars({ buckets, unit }: { buckets: RunBucket[]; unit: 'day' | 'hour' }): JSX.Element {
    const peak = Math.max(1, ...buckets.map((bucket) => bucket.successful + bucket.failed))
    const succeeded = buckets.reduce((sum, bucket) => sum + bucket.successful, 0)
    const failed = buckets.reduce((sum, bucket) => sum + bucket.failed, 0)

    return (
        <div
            role="img"
            aria-label={`Runs per ${unit}: ${succeeded} succeeded, ${failed} failed`}
            className="flex h-6 items-end gap-px"
        >
            {buckets.map((bucket) => (
                <div
                    key={bucket.key}
                    title={`${bucket.key.replace('T', ' ')}${unit === 'hour' ? ':00' : ''}: ${bucket.successful} succeeded, ${bucket.failed} failed`}
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
    )
}
