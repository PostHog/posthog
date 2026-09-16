import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

// Example deciles - hand-authored, not real data. The bimodal shape a healthy
// churn/conversion model produces: most users cold, a hot tail worth acting on.
const DECILE_USERS = [412, 188, 96, 61, 44, 32, 25, 21, 18, 74]

const TOP_USERS = [
    { user: 'sofia', probability: '96.2%' },
    { user: 'liam', probability: '93.8%' },
    { user: 'ava', probability: '91.4%' },
]

/**
 * Example-data preview for the autoresearch empty state: the probability
 * distribution plus the highest-probability users - static bars, no timers, per
 * the preview rules in the `building-product-empty-states` skill.
 */
export function AutoresearchPredictionPreview(_: { mode: ProductEmptyStateMode }): JSX.Element {
    const maxUsers = Math.max(...DECILE_USERS)
    return (
        <div className="flex flex-col gap-3">
            <div className="rounded-md border border-primary bg-surface-primary p-3">
                <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-semibold">Probability of converting · next 30 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="flex items-end gap-1 h-20">
                    {DECILE_USERS.map((users, decile) => (
                        <div key={decile} className="flex-1 flex flex-col justify-end h-full">
                            <div
                                className="w-full rounded-t bg-[var(--data-color-1)]"
                                style={{ height: `${Math.max(4, (100 * users) / maxUsers)}%` }}
                            />
                        </div>
                    ))}
                </div>
                <div className="mt-1 flex justify-between text-xs text-secondary">
                    <span>0%</span>
                    <span>100%</span>
                </div>
            </div>

            <div className="rounded-md border border-primary bg-surface-primary p-3">
                <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-semibold">Highest-probability users</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="flex flex-col">
                    {TOP_USERS.map((row) => (
                        <div
                            key={row.user}
                            className="flex items-center gap-2 border-b border-primary px-1 py-1.5 text-xs last:border-b-0"
                        >
                            <span className="min-w-0 truncate font-medium">{row.user}</span>
                            <span className="ml-auto shrink-0 text-secondary tabular-nums">{row.probability}</span>
                        </div>
                    ))}
                </div>
                <div className="mt-2 rounded border border-primary px-2 py-1.5 text-xs text-secondary">
                    Written back as the <span className="font-semibold text-primary">predicted_p_converted</span> person
                    property
                </div>
            </div>
        </div>
    )
}
