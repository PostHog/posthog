import './BillingGauge.scss'

import clsx from 'clsx'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { compactNumber } from 'lib/utils'
import { useMemo } from 'react'

import { BillingGaugeItem } from './types'

type BillingGaugeItemProps = {
    item: BillingGaugeItem
    maxValue: number
}

const BillingGaugeItem = ({ item, maxValue }: BillingGaugeItemProps): JSX.Element => {
    const width = `${(item.value / maxValue) * 100}%`
    const colorClassName = `bg-${item.color}`

    return (
        <div
            className={`BillingGaugeItem absolute top-0 left-0 bottom-0 h-2 ${colorClassName}`}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--billing-gauge-item-width': width } as React.CSSProperties}
        >
            <div className="absolute right-0 w-px h-full bg-bg-light" />
            <Tooltip title={item.value.toLocaleString()} placement={'right'}>
                <div
                    className={clsx('BillingGaugeItem__info', {
                        'BillingGaugeItem__info--bottom': !item.top,
                    })}
                >
                    <b>{item.text}</b>
                    <div>{compactNumber(item.value)}</div>
                </div>
            </Tooltip>
        </div>
    )
}

export type BillingGaugeProps = {
    items: BillingGaugeItem[]
}

export function BillingGauge({ items }: BillingGaugeProps): JSX.Element {
    const maxValue = useMemo(() => {
        return Math.max(100, ...items.map((item) => item.value)) * 1.3
    }, [items])

    return (
        <div className="relative h-2 bg-border-light my-16">
            {items.map((item, i) => (
                <BillingGaugeItem key={i} item={item} maxValue={maxValue} />
            ))}
        </div>
    )
}
