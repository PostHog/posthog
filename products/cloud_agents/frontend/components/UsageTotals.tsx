import { LemonCard } from '@posthog/lemon-ui'

import type { CloudAgentUsageTotalsApi } from '../generated/api.schemas'
import { formatCost, formatSecondsAsHours } from '../utils/pricing'

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex min-w-0 flex-col p-3">
            <span className="text-secondary text-xs">{label}</span>
            <span className="text-xl font-bold tabular-nums" translate="no">
                {value}
            </span>
            {hint && <span className="text-secondary text-xs">{hint}</span>}
        </LemonCard>
    )
}

export function UsageTotals({ totals }: { totals: CloudAgentUsageTotalsApi }): JSX.Element {
    return (
        <div
            className="grid grid-cols-2 gap-3 @min-[40rem]/main-content:grid-cols-3 @min-[64rem]/main-content:grid-cols-6"
            data-attr="cloud-agents-usage-totals"
        >
            <Stat label="Total" value={formatCost(totals.total_usd)} />
            <Stat label="Compute" value={formatCost(totals.compute_usd)} />
            <Stat label="Model usage" value={formatCost(totals.inference_usd)} hint="Billed by PostHog only" />
            <Stat label="Runs" value={totals.runs.toLocaleString('en-US')} />
            <Stat label="vCPU-hours" value={formatSecondsAsHours(totals.vcpu_seconds)} />
            <Stat label="GiB-hours" value={formatSecondsAsHours(totals.gib_seconds)} />
        </div>
    )
}
