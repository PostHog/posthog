import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { compactNumber } from 'lib/utils'

import { BillingProductV2Type, BillingTierType } from '~/types'

function formatPrice(price: string | number): string {
    const numPrice = typeof price === 'string' ? parseFloat(price) : price
    if (numPrice === 0) {
        return 'Free'
    }
    return `$${numPrice.toFixed(6).replace(/\.?0+$/, '')}`
}

function getTierName(tier: BillingTierType, index: number, tiers: BillingTierType[]): string {
    if (index === 0 && tier.up_to) {
        return `First ${compactNumber(tier.up_to)} rows`
    }

    const previousTier = index > 0 ? tiers[index - 1] : null
    const start = previousTier?.up_to ? compactNumber(previousTier.up_to) : '0'

    if (tier.up_to) {
        return `${start} - ${compactNumber(tier.up_to)} rows`
    }

    return `${start}+ rows`
}

type TierGaugeProps = {
    tier: BillingTierType
    index: number
    tiers: BillingTierType[]
    unit: string
}

function TierGauge({ tier, index, tiers, unit }: TierGaugeProps): JSX.Element {
    const tierName = getTierName(tier, index, tiers)
    const unitPrice = parseFloat(tier.unit_amount_usd || '0')
    const currentCost = parseFloat(tier.current_amount_usd || '0')

    const previousTier = index > 0 ? tiers[index - 1] : null
    const tierStart = previousTier?.up_to || 0
    const tierCapacity = tier.up_to ? tier.up_to - tierStart : Math.max(tier.current_usage, tier.projected_usage || 0)

    const currentPercentage = tierCapacity === 0 ? 0 : Math.min(100, (tier.current_usage / tierCapacity) * 100)
    const projectedPercentage =
        tier.projected_usage !== null && tierCapacity > 0
            ? Math.min(100, (tier.projected_usage / tierCapacity) * 100)
            : currentPercentage

    const hasProjected = tier.projected_usage !== null && tier.projected_usage !== tier.current_usage
    const projectedCost = parseFloat(tier.projected_amount_usd || '0')

    return (
        <div className="border rounded-lg p-4 bg-bg-light hover:bg-bg-3000 transition-colors">
            <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                    <div className="font-medium text-sm mb-1">{tierName}</div>
                    <div className="text-xs text-muted">
                        {unitPrice === 0 ? (
                            'Free tier'
                        ) : (
                            <>
                                {formatPrice(unitPrice)} per {unit}
                            </>
                        )}
                    </div>
                </div>
                <div className="text-right">
                    <div className="text-xl font-semibold">${currentCost.toFixed(2)}</div>
                    <div className="text-xs text-muted">{compactNumber(tier.current_usage)} rows</div>
                </div>
            </div>

            <div className="relative h-2 bg-border-light rounded overflow-hidden mb-3">
                {/* Current usage bar */}
                <Tooltip
                    title={`Current: ${compactNumber(tier.current_usage)} rows ($${currentCost.toFixed(2)})`}
                    placement="top"
                >
                    <div
                        className="absolute top-0 left-0 bottom-0 rounded z-[2] transition-all duration-700"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            width: `${currentPercentage}%`,
                            background: 'var(--brand-blue)',
                            transitionTimingFunction: 'cubic-bezier(0.15, 0.15, 0.2, 1)',
                        }}
                    />
                </Tooltip>

                {/* Projected usage bar (if different) */}
                {hasProjected && (
                    <Tooltip
                        title={`Projected: ${compactNumber(tier.projected_usage || 0)} rows ($${projectedCost.toFixed(2)})`}
                        placement="top"
                    >
                        <div
                            className="absolute top-0 left-0 bottom-0 rounded opacity-50 z-[1] transition-all duration-700"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                width: `${projectedPercentage}%`,
                                background:
                                    'repeating-linear-gradient(-45deg, var(--data-color-1), var(--data-color-1) 0.5rem, var(--data-color-1-hover) 0.5rem, var(--data-color-1-hover) 1rem)',
                                transitionTimingFunction: 'cubic-bezier(0.15, 0.15, 0.2, 1)',
                            }}
                        />
                    </Tooltip>
                )}

                {/* Labels */}
                <div className="flex flex-col gap-1 mt-2 text-sm">
                    <div className="flex items-center gap-2">
                        <span
                            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ background: 'var(--brand-blue)' }}
                        />
                        <span className="font-medium">{compactNumber(tier.current_usage)} rows</span>
                    </div>
                    {hasProjected && (
                        <div className="flex items-center gap-2">
                            <span
                                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    background:
                                        'repeating-linear-gradient(-45deg, var(--data-color-1), var(--data-color-1) 0.125rem, var(--data-color-1-hover) 0.125rem, var(--data-color-1-hover) 0.25rem)',
                                }}
                            />
                            <span className="text-muted">
                                Projected: {compactNumber(tier.projected_usage || 0)} rows · ${projectedCost.toFixed(2)}
                            </span>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

export function DataWarehouseTierBreakdown({ product }: { product: BillingProductV2Type }): JSX.Element {
    if (!product.tiers || product.tiers.length === 0) {
        return <div className="text-muted">No tier data available</div>
    }

    return (
        <div className="space-y-3">
            {product.tiers.map((tier, index) => (
                <TierGauge key={index} tier={tier} index={index} tiers={product.tiers!} unit={product.unit || 'row'} />
            ))}
        </div>
    )
}
