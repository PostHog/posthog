import clsx from 'clsx'
import { compactNumber } from 'lib/utils'
import React, { useEffect, useMemo, useState } from 'react'
import './BillingGuage.scss'

type BillingGuageItemProps = {
    width: string
    className: string
    tooltip: string | JSX.Element
    top: boolean
    value: number
}

const BillingGuageItem = ({ width, className, tooltip, top, value }: BillingGuageItemProps): JSX.Element => {
    return (
        <div
            className={`BillingGuageItem absolute top-0 left-0 bottom-0 h-2 ${className}`}
            style={{
                width: width,
            }}
        >
            <div className="absolute right-0 w-px h-full bg-light" />
            <div
                className={clsx('BillingGuageItem__info', {
                    'BillingGuageItem__info--bottom': !top,
                })}
            >
                {tooltip}
                <div>{compactNumber(value)}</div>
            </div>
        </div>
    )
}

export type BillingGuageProps = {
    items: {
        tooltip: string | JSX.Element
        color: string
        value: number
        top: boolean
    }[]
}

export function BillingGuage({ items }: BillingGuageProps): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const maxScale = useMemo(() => {
        return Math.max(100, ...items.map((item) => item.value)) * 1.2
    }, [items])

    useEffect(() => {
        setExpanded(true)
    }, [])

    return (
        <div className="relative h-2 bg-border-light my-16">
            {items.map((item, i) => (
                <BillingGuageItem
                    key={i}
                    width={expanded ? `${(item.value / maxScale) * 100}%` : '0%'}
                    className={`bg-${item.color}`}
                    tooltip={item.tooltip}
                    top={item.top}
                    value={item.value}
                />
            ))}
        </div>
    )
}
