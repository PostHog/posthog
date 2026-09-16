import { Tooltip } from '@posthog/lemon-ui'

import { ProbabilityBucket } from './autoresearchPipelineLogic'

// The h-40 track minus room for the count label above the tallest bar.
const BAR_MAX_HEIGHT_PX = 136

/** Fixed-decile histogram of a scoring run's predicted probabilities. No chart deps, like MetricSparkline. */
export function ProbabilityHistogram({ buckets }: { buckets: ProbabilityBucket[] }): JSX.Element {
    const totalUsers = buckets.reduce((sum, bucket) => sum + bucket.users, 0)
    const maxUsers = Math.max(...buckets.map((bucket) => bucket.users), 1)
    return (
        <div className="flex items-end gap-2 max-w-4xl">
            {buckets.map((bucket) => {
                const label = `${Math.round(bucket.lower * 100)}-${Math.round((bucket.lower + 0.1) * 100)}%`
                const share = totalUsers > 0 ? (100 * bucket.users) / totalUsers : 0
                return (
                    <Tooltip
                        key={bucket.lower}
                        title={`${label}: ${bucket.users.toLocaleString()} users (${share.toFixed(1)}% of ${totalUsers.toLocaleString()} scored)`}
                    >
                        <div className="flex-1 min-w-0 flex flex-col items-center gap-1">
                            <div className="w-full h-40 flex flex-col items-center justify-end gap-0.5">
                                <span
                                    className={`text-xs tabular-nums ${bucket.users > 0 ? 'text-secondary' : 'text-muted'}`}
                                >
                                    {bucket.users.toLocaleString()}
                                </span>
                                <div
                                    className="w-full rounded-t bg-[var(--data-color-1)] hover:bg-[var(--data-color-1-hover)]"
                                    style={{
                                        height: Math.round((BAR_MAX_HEIGHT_PX * bucket.users) / maxUsers),
                                        minHeight: bucket.users > 0 ? 3 : 0,
                                    }}
                                />
                            </div>
                            <span className="text-xs text-muted whitespace-nowrap">{label}</span>
                        </div>
                    </Tooltip>
                )
            })}
        </div>
    )
}
