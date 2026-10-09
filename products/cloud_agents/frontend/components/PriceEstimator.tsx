import { useActions, useValues } from 'kea'

import { LemonCard, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { cloudAgentsUsageLogic } from '../logics/cloudAgentsUsageLogic'
import { formatCost, formatMinutes, formatRate } from '../utils/pricing'
import { BoxSizeSelect } from './BoxSizeSelect'

/** Works out the compute price of a run from the catalog rates. Nothing leaves the browser, so the answer is instant. */
export function PriceEstimator(): JSX.Element {
    const { estimatorSize, estimatorMinutes, estimate } = useValues(cloudAgentsUsageLogic)
    const { setEstimatorSize, setEstimatorMinutes } = useActions(cloudAgentsUsageLogic)

    return (
        <LemonCard
            hoverEffect={false}
            className="flex min-w-0 flex-col gap-3 p-4"
            data-attr="cloud-agents-price-estimator"
        >
            <div>
                <h3 className="m-0 text-base font-semibold">Price estimator</h3>
                <p className="m-0 text-secondary text-xs">See what a run costs before you start it.</p>
            </div>
            <div className="grid grid-cols-1 gap-3 @min-[30rem]/main-content:grid-cols-3">
                <div className="flex flex-col gap-1 @min-[30rem]/main-content:col-span-2">
                    <LemonLabel>Box size</LemonLabel>
                    <BoxSizeSelect
                        value={estimatorSize?.name ?? null}
                        onChange={(size) => size && setEstimatorSize(size)}
                        data-attr="cloud-agents-estimator-size"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Minutes</LemonLabel>
                    <LemonInput
                        type="number"
                        min={1}
                        value={estimatorMinutes}
                        onChange={(minutes) => setEstimatorMinutes(Math.max(0, Math.round(minutes ?? 0)))}
                        data-attr="cloud-agents-estimator-minutes"
                    />
                </div>
            </div>
            {estimate && (
                <div className="rounded border bg-surface-secondary p-3">
                    <div className="text-2xl font-bold tabular-nums" translate="no">
                        {formatCost(estimate.estimateUsd)}
                    </div>
                    <div className="text-secondary text-xs" translate="no">
                        {formatRate(estimate.pricePerHourUsd)} per hour for {formatMinutes(estimate.minutes)} of compute
                    </div>
                </div>
            )}
            <p className="m-0 text-secondary text-xs">
                Compute is billed per second on the selected size, so a run that ends early costs less. Model usage is
                not in this estimate: it is billed separately in AI credits, or by your provider when you bring your own
                subscription.
            </p>
        </LemonCard>
    )
}
