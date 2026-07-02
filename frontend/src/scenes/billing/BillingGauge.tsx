import './BillingGauge.scss'

import clsx from 'clsx'
import { useMemo } from 'react'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import { BillingProductV2AddonType, BillingProductV2Type, BillingType } from '~/types'

import {
    convertUsageToAmount,
    createProductValueFormatter,
    formatDisplayUsage,
    hasDisplayFormatting,
} from './billing-utils'
import { BillingGaugeItemKind, BillingGaugeItemType } from './types'

/**
 * The USD amount a user will actually be charged for `usage` units of a tiered product,
 * i.e. the cost of the portion of usage that sits at or below their billing limit.
 * Returns null when we can't price the usage (non-tiered products).
 */
const getPaidAmountUsd = (
    usage: number,
    product?: BillingProductV2Type | BillingProductV2AddonType,
    discountPercent?: number
): number | null => {
    if (!product?.tiers) {
        return null
    }
    return parseFloat(convertUsageToAmount(usage, [product.tiers], discountPercent))
}

/*
 * Billing Gauge Item: Individual bars on the billing gauge.
 */
type BillingGaugeItemProps = {
    item: BillingGaugeItemType
    maxValue: number
    isWithinUsageLimit: boolean
    isTop: boolean
    product?: BillingProductV2Type | BillingProductV2AddonType
    /** Usage value of the billing limit, when the product has one set. */
    billingLimit?: number
    discountPercent?: number
}

const BillingGaugeItem = ({
    item,
    maxValue,
    isWithinUsageLimit,
    isTop,
    product,
    billingLimit,
    discountPercent,
}: BillingGaugeItemProps): JSX.Element => {
    const width = `${(item.value / maxValue) * 100}%`

    const formatValue = product ? createProductValueFormatter(product) : (v: number | null) => v?.toLocaleString() ?? ''
    const formattedValue = formatValue(item.value)
    const tooltipValue =
        product && hasDisplayFormatting(product) ? formatDisplayUsage(item.value, product) : item.value.toLocaleString()

    // Split the current usage bar at the billing limit: the part at or below the limit is what the
    // user pays for (solid), the part above is not charged (striped + desaturated). We only do this on
    // usage gauges (not the monetary `$` gauge, which carries a `prefix`) where a limit is actually set.
    const hasLimit =
        item.type === BillingGaugeItemKind.CurrentUsage && !item.prefix && !!billingLimit && billingLimit > 0
    const isOverLimit = hasLimit && item.value > (billingLimit as number)
    const paidUsage = hasLimit ? Math.min(item.value, billingLimit as number) : item.value
    const paidAmountUsd = hasLimit ? getPaidAmountUsd(paidUsage, product, discountPercent) : null
    // Fraction of this bar (which spans 0..item.value) that sits at or below the limit.
    const paidFraction = isOverLimit ? (billingLimit as number) / item.value : 1

    // Scoped to this product because we price only its tiers, not any addons folded into the total.
    const paidLabel =
        paidAmountUsd !== null
            ? `What you'll pay for ${product?.name ?? 'this'}: ${humanFriendlyCurrency(paidAmountUsd)}`
            : 'Usage you pay for'

    return (
        <div
            className={clsx(
                `BillingGaugeItem BillingGaugeItem--${item.type}`,
                {
                    'BillingGaugeItem--within-usage-limit': isWithinUsageLimit,
                    'BillingGaugeItem--split': isOverLimit,
                },
                'absolute top-0 left-0 bottom-0 h-2'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--billing-gauge-item-width': width } as React.CSSProperties}
        >
            {isOverLimit ? (
                <>
                    <Tooltip title={paidLabel}>
                        <div
                            className="BillingGaugeItem__section BillingGaugeItem__section--paid absolute top-0 bottom-0 left-0"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: `${paidFraction * 100}%` }}
                        />
                    </Tooltip>
                    <Tooltip title="You won't be charged for usage above your billing limit">
                        <div
                            className="BillingGaugeItem__section BillingGaugeItem__section--over-limit absolute top-0 bottom-0 right-0"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ left: `${paidFraction * 100}%` }}
                        />
                    </Tooltip>
                </>
            ) : (
                hasLimit &&
                paidAmountUsd !== null && (
                    <Tooltip title={paidLabel}>
                        <div className="BillingGaugeItem__section absolute inset-0" />
                    </Tooltip>
                )
            )}
            <div className="absolute right-0 w-px h-full bg-surface-primary" />
            <Tooltip title={item.prefix ? `${item.prefix}${tooltipValue}` : tooltipValue} placement="right">
                <div
                    className={clsx('BillingGaugeItem__info', {
                        'BillingGaugeItem__info--bottom': !isTop,
                    })}
                >
                    <b>{item.text}</b>
                    <div>{item.prefix ? `${item.prefix}${formattedValue}` : formattedValue}</div>
                </div>
            </Tooltip>
        </div>
    )
}

/*
 * Billing Gauge.
 */
export type BillingGaugeProps = {
    items: BillingGaugeItemType[]
    product: BillingProductV2Type | BillingProductV2AddonType
    billing?: BillingType | null
}

export function BillingGauge({ items, product, billing }: BillingGaugeProps): JSX.Element {
    const maxValue = useMemo(() => {
        return Math.max(100, ...items.map((item) => item.value)) * 1.3
    }, [items])
    const isWithinUsageLimit = (product.percentage_usage ?? 0) <= 1

    const sortedItems = useMemo(() => {
        return [...items].sort((a, b) => a.value - b.value)
    }, [items])

    const billingLimit = useMemo(
        () => items.find((item) => item.type === BillingGaugeItemKind.BillingLimit)?.value,
        [items]
    )
    const discountPercent = billing?.discount_percent || undefined

    return (
        <div className="relative h-2 bg-border-light my-16">
            {sortedItems.map((item, i) => (
                <BillingGaugeItem
                    key={i}
                    item={item}
                    maxValue={maxValue}
                    isWithinUsageLimit={isWithinUsageLimit}
                    isTop={i % 2 !== 0}
                    product={product}
                    billingLimit={billingLimit}
                    discountPercent={discountPercent}
                />
            ))}
        </div>
    )
}
