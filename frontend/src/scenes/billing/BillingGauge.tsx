import './BillingGauge.scss'

import clsx from 'clsx'
import { useMemo } from 'react'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { compactNumber } from 'lib/utils'

import { BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { BillingGaugeItemType } from './types'

/*
 * Billing Gauge Item: Individual bars on the billing gauge.
 */
type BillingGaugeItemProps = {
    item: BillingGaugeItemType
    maxValue: number
    isWithinUsageLimit: boolean
    isTop: boolean
}

const BillingGaugeItem = ({ item, maxValue, isWithinUsageLimit, isTop }: BillingGaugeItemProps): JSX.Element => {
    const width = `${(item.value / maxValue) * 100}%`

    return (
        <div
            className={clsx(
                `BillingGaugeItem BillingGaugeItem--${item.type}`,
                {
                    'BillingGaugeItem--within-usage-limit': isWithinUsageLimit,
                },
                'absolute top-0 left-0 bottom-0 h-2'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--billing-gauge-item-width': width } as React.CSSProperties}
        >
            <div className="absolute right-0 w-px h-full bg-surface-primary" />
            <Tooltip
                title={item.prefix ? `${item.prefix}${item.value.toLocaleString()}` : item.value.toLocaleString()}
                placement="right"
            >
                <div
                    className={clsx('BillingGaugeItem__info', {
                        'BillingGaugeItem__info--bottom': !isTop,
                    })}
                >
                    <b>{item.text}</b>
                    <div>{item.prefix ? `${item.prefix}${compactNumber(item.value)}` : compactNumber(item.value)}</div>
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
}

export function BillingGauge({ items, product }: BillingGaugeProps): JSX.Element {
    const maxValue = useMemo(() => {
        return Math.max(100, ...items.map((item) => item.value)) * 1.3
    }, [items])
    const isWithinUsageLimit = (product.percentage_usage ?? 0) <= 1

    const sortedItems = useMemo(() => {
        return [...items].sort((a, b) => a.value - b.value)
    }, [items])

    return (
        <div className="relative h-2 bg-border-light my-16">
            {sortedItems.map((item, i) => (
                <BillingGaugeItem
                    key={i}
                    item={item}
                    maxValue={maxValue}
                    isWithinUsageLimit={isWithinUsageLimit}
                    isTop={i % 2 !== 0}
                />
            ))}
        </div>
    )
}
