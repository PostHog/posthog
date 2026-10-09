import { LemonCard, LemonTag } from '@posthog/lemon-ui'

import type { CloudAgentRunApi } from '../generated/api.schemas'
import { BillingModeEnumApi } from '../generated/api.schemas'
import { formatBoxSize, formatCost, formatRate, formatSeconds } from '../utils/pricing'
import { INFERENCE_BILLING_LABELS } from '../utils/runStatus'

function CostRow({ label, value, hint }: { label: string; value: string; hint?: string }): JSX.Element {
    return (
        <div className="flex items-baseline justify-between gap-4">
            <dt className="text-secondary font-normal">{label}</dt>
            <dd className="m-0 text-right">
                <span className="tabular-nums font-medium" translate="no">
                    {value}
                </span>
                {hint && <div className="text-secondary text-xs">{hint}</div>}
            </dd>
        </div>
    )
}

/** What a run cost and why: the two parts of the bill, the usage behind the compute part, and who pays for the model. */
export function RunCostCard({ run }: { run: CloudAgentRunApi }): JSX.Element {
    const { cost, config } = run
    const unbilled = cost.billing_mode === BillingModeEnumApi.Unbilled
    const inferencePayer = cost.inference_billing ? INFERENCE_BILLING_LABELS[cost.inference_billing] : null
    const ownProvider = cost.inference_billing !== null && cost.inference_billing !== 'posthog'

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4" data-attr="cloud-agents-run-cost-card">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="m-0 text-base font-semibold">Cost</h3>
                <div className="flex flex-wrap gap-1">
                    {unbilled && <LemonTag type="success">Not billed</LemonTag>}
                    {!cost.final && <LemonTag type="warning">Settling</LemonTag>}
                </div>
            </div>
            <div>
                <div className="text-3xl font-bold tabular-nums" translate="no">
                    {formatCost(cost.total_usd)}
                </div>
                <div className="text-secondary text-xs">
                    {unbilled
                        ? 'You are not charged for this run.'
                        : cost.final
                          ? ownProvider
                              ? 'Total for compute. Model usage counts against your subscription.'
                              : 'Total for compute and model usage.'
                          : 'The cost so far. It can still change until the run settles.'}
                </div>
            </div>
            <dl className="m-0 flex flex-col gap-2 border-t pt-3">
                <CostRow label="Compute" value={formatCost(cost.compute_usd)} />
                <CostRow
                    label="Model usage"
                    value={cost.inference_usd === null ? 'Not billed by PostHog' : formatCost(cost.inference_usd)}
                    hint={inferencePayer ? `Paid with: ${inferencePayer}` : undefined}
                />
                <CostRow
                    label="Box size"
                    value={formatBoxSize(config.size)}
                    hint={`${formatRate(config.size.price_per_hour_usd)} per hour, billed per second`}
                />
                <CostRow label="vCPU-seconds" value={formatSeconds(cost.vcpu_seconds)} />
                <CostRow label="GiB-seconds" value={formatSeconds(cost.gib_seconds)} />
            </dl>
        </LemonCard>
    )
}
