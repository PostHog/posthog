import { Tooltip } from '@posthog/lemon-ui'

import type { CloudAgentRunCostApi } from '../generated/api.schemas'
import { BillingModeEnumApi, InferenceBillingEnumApi } from '../generated/api.schemas'
import { formatCost } from '../utils/pricing'

/** The total cost of a run in a table row, with a hint when the number can still change or leaves something out. */
export function RunCostCell({ cost }: { cost: CloudAgentRunCostApi }): JSX.Element {
    const ownProvider = cost.inference_billing === InferenceBillingEnumApi.OwnSubscription
    const hints: string[] = []
    if (cost.billing_mode === BillingModeEnumApi.Unbilled) {
        hints.push('Not billed')
    }
    if (!cost.final) {
        hints.push('Settling')
    }
    if (ownProvider) {
        hints.push('Your subscription')
    }
    return (
        <Tooltip
            title={
                ownProvider
                    ? 'Compute only. The model usage of this run counts against your subscription.'
                    : cost.final
                      ? undefined
                      : 'This cost can still change until the run settles.'
            }
        >
            <div className="flex flex-col">
                <span className="font-semibold tabular-nums" translate="no">
                    {formatCost(cost.total_usd)}
                </span>
                {hints.length > 0 && (
                    <span className="text-secondary text-xs whitespace-nowrap">{hints.join(' · ')}</span>
                )}
            </div>
        </Tooltip>
    )
}
