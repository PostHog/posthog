import './BillingGauge.scss'

import clsx from 'clsx'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { compactNumber } from 'lib/utils'
import { useMemo } from 'react'

type BillingGaugeItemProps = {
    width: string
    className: string
    tooltip: string | JSX.Element
    top: boolean
    value: number
}

const BillingGaugeItem = ({ width, className, tooltip, top, value }: BillingGaugeItemProps): JSX.Element => {
    return (
        <div
            className={`BillingGaugeItem absolute top-0 left-0 bottom-0 h-2 ${className}`}
            style={{ '--billing-gauge-item-width': width } as React.CSSProperties}
        >
            <div className="absolute right-0 w-px h-full bg-bg-light" />
            <Tooltip title={value.toLocaleString()} placement={'right'}>
                <div
                    className={clsx('BillingGaugeItem__info', {
                        'BillingGaugeItem__info--bottom': !top,
                    })}
                >
                    {tooltip}
                    <div>{compactNumber(value)}</div>
                </div>
            </Tooltip>
        </div>
    )
}

export type BillingGaugeProps = {
    items: {
        text: string | JSX.Element
        color: string
        value: number
        top: boolean
    }[]
}

export function BillingGauge({ items }: BillingGaugeProps): JSX.Element {
    const maxScale = useMemo(() => {
        return Math.max(100, ...items.map((item) => item.value)) * 1.3
    }, [items])

    return (
        <div className="relative h-2 bg-border-light my-16">
            {items.map((item, i) => (
                <BillingGaugeItem
                    key={i}
                    width={`${(item.value / maxScale) * 100}%`}
                    className={`bg-${item.color}`}
                    tooltip={<b>{item.text}</b>}
                    top={item.top}
                    value={item.value}
                />
            ))}
        </div>
    )
}
