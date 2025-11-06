import { LemonCard } from '@posthog/lemon-ui'

import { BillingProductV2Type } from '~/types'

import { DataWarehouseTierBreakdown } from './DataWarehouseTierBreakdown'

export function DataWarehousePricingCard({ product }: { product: BillingProductV2Type | null }): JSX.Element {
    if (!product || !product.tiers || product.tiers.length === 0) {
        return (
            <LemonCard className="hover:transform-none">
                <div>
                    <h2 className="text-xl font-semibold mb-3">Cost breakdown</h2>
                    <div className="py-8 text-center text-muted">
                        <div className="mb-2">No billing data available</div>
                        <div className="text-xs">Cost breakdown will appear when you have usage data</div>
                    </div>
                </div>
            </LemonCard>
        )
    }

    const currentTotal = parseFloat(product.current_amount_usd || '0')
    const projectedTotal = parseFloat(product.projected_amount_usd || '0')
    const hasProjected = projectedTotal !== currentTotal

    return (
        <LemonCard className="hover:transform-none">
            <div className="pb-4">
                <h2 className="text-xl font-semibold mb-3">Cost breakdown</h2>
                <div className="flex items-center justify-between py-3 px-4 bg-bg-3000 rounded border">
                    <div className="text-center flex-1">
                        <div className="text-xs text-muted mb-1">Current period</div>
                        <div className="text-2xl font-bold">${currentTotal.toFixed(2)}</div>
                    </div>
                    {hasProjected && (
                        <div className="text-center flex-1">
                            <div className="text-xs text-muted mb-1">Projected total</div>
                            <div className="text-2xl font-bold text-muted-3000">${projectedTotal.toFixed(2)}</div>
                        </div>
                    )}
                </div>
            </div>
            <DataWarehouseTierBreakdown product={displayProduct} />
        </LemonCard>
    )
}
