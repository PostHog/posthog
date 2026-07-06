import './BillingGauge.scss'

import clsx from 'clsx'
import { useLayoutEffect, useMemo, useRef, useState } from 'react'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import {
    createProductValueFormatter,
    formatDisplayUsage,
    hasDisplayFormatting,
    isAlertOnlyProduct,
} from './billing-utils'
import { BillingGaugeItemType } from './types'

// Where a label sits relative to the bar: which side, and how many rows out from it. depth > 0 means
// the label was stacked further from the bar to avoid overlapping a closer label on the same side.
type LabelPlacement = { isTop: boolean; depth: number }

// Fallback label-row height (px) before labels have been measured.
const FALLBACK_ROW_HEIGHT_PX = 34
// Minimum horizontal gap (px) two labels must keep on the same row before one is stacked.
const LABEL_HGAP_PX = 8

const placementsEqual = (a: LabelPlacement[], b: LabelPlacement[]): boolean =>
    a.length === b.length && a.every((p, i) => p.isTop === b[i].isTop && p.depth === b[i].depth)

/*
 * Billing Gauge Item: Individual bars on the billing gauge.
 */
type BillingGaugeItemProps = {
    item: BillingGaugeItemType
    maxValue: number
    isWithinUsageLimit: boolean
    placement: LabelPlacement
    rowHeight: number
    product?: BillingProductV2Type | BillingProductV2AddonType
    valueFormatter?: (value: number | null) => string
}

const BillingGaugeItem = ({
    item,
    maxValue,
    isWithinUsageLimit,
    placement,
    rowHeight,
    product,
    valueFormatter,
}: BillingGaugeItemProps): JSX.Element => {
    const width = `${(item.value / maxValue) * 100}%`

    // An explicit valueFormatter wins (e.g. the combined dollar gauge, whose values aren't in the
    // product's unit); otherwise format from the product's display config.
    const formatValue =
        valueFormatter ??
        (product ? createProductValueFormatter(product) : (v: number | null) => v?.toLocaleString() ?? '')
    const formattedValue = formatValue(item.value)
    const tooltipValue = valueFormatter
        ? valueFormatter(item.value)
        : product && hasDisplayFormatting(product)
          ? formatDisplayUsage(item.value, product)
          : item.value.toLocaleString()

    // Push the label away from the bar (up for top labels, down for bottom) when it's been stacked.
    const offset = placement.depth * rowHeight

    return (
        <div
            className={clsx(
                `BillingGaugeItem BillingGaugeItem--${item.type}`,
                {
                    'BillingGaugeItem--within-usage-limit': isWithinUsageLimit,
                    'BillingGaugeItem--alert-only': product
                        ? isAlertOnlyProduct(product) && !!product.subscribed
                        : false,
                },
                'absolute top-0 left-0 bottom-0 h-2'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--billing-gauge-item-width': width } as React.CSSProperties}
        >
            <div className="absolute right-0 w-px h-full bg-surface-primary" />
            <Tooltip title={item.prefix ? `${item.prefix}${tooltipValue}` : tooltipValue} placement="right">
                <div
                    className={clsx('BillingGaugeItem__info', {
                        'BillingGaugeItem__info--bottom': !placement.isTop,
                    })}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={offset ? { transform: `translateY(${placement.isTop ? -offset : offset}px)` } : undefined}
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
    /** Overrides product-derived formatting — for gauges whose values aren't in the product's unit. */
    valueFormatter?: (value: number | null) => string
}

export function BillingGauge({ items, product, valueFormatter }: BillingGaugeProps): JSX.Element {
    const maxValue = useMemo(() => {
        return Math.max(100, ...items.map((item) => item.value)) * 1.3
    }, [items])
    const isWithinUsageLimit = (product.percentage_usage ?? 0) <= 1

    const sortedItems = useMemo(() => {
        return [...items].sort((a, b) => a.value - b.value)
    }, [items])

    const containerRef = useRef<HTMLDivElement>(null)
    const [placements, setPlacements] = useState<LabelPlacement[]>([])
    const [rowHeight, setRowHeight] = useState(FALLBACK_ROW_HEIGHT_PX)

    // Call sites often pass a freshly-built items array on every render; keying the layout effect
    // on the VALUES (not array identity) avoids re-measuring the DOM and reconnecting the
    // ResizeObserver on unrelated re-renders. The ref keeps the effect reading current items.
    const sortedItemsRef = useRef(sortedItems)
    sortedItemsRef.current = sortedItems
    const itemsKey = sortedItems
        .map((item) => `${item.value}:${typeof item.text === 'string' ? item.text : item.type}`)
        .join('|')

    // Keep each label on its original side (top/bottom alternating), but when it would overlap a
    // closer label on that side, stack it one row further out. Measured from the DOM so it adapts to
    // real label widths and the container's rendered width, and recomputed on resize.
    useLayoutEffect(() => {
        const container = containerRef.current
        if (!container) {
            return
        }
        const recompute = (): void => {
            const containerWidth = container.offsetWidth
            if (!containerWidth) {
                return
            }
            // Labels render in sorted order, so the Nth `.BillingGaugeItem__info` maps to sortedItems[N].
            const labelEls = container.querySelectorAll<HTMLElement>('.BillingGaugeItem__info')
            const topRowEnds: number[] = []
            const bottomRowEnds: number[] = []
            let measuredRowHeight = 0
            const next = sortedItemsRef.current.map((item, i): LabelPlacement => {
                const isTop = i % 2 !== 0
                const labelEl = labelEls[i]
                const labelWidth = labelEl?.offsetWidth ?? 0
                measuredRowHeight = Math.max(measuredRowHeight, labelEl?.offsetHeight ?? 0)
                const left = (item.value / maxValue) * containerWidth
                const rowEnds = isTop ? topRowEnds : bottomRowEnds
                let depth = 0
                while (rowEnds[depth] !== undefined && rowEnds[depth] + LABEL_HGAP_PX > left) {
                    depth++
                }
                rowEnds[depth] = left + labelWidth
                return { isTop, depth }
            })
            setPlacements((prev) => (placementsEqual(prev, next) ? prev : next))
            if (measuredRowHeight) {
                const nextRowHeight = measuredRowHeight + 4
                setRowHeight((prev) => (prev === nextRowHeight ? prev : nextRowHeight))
            }
        }
        recompute()
        const observer = new ResizeObserver(recompute)
        observer.observe(container)
        return () => observer.disconnect()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [itemsKey, maxValue])

    // Reserve vertical room for however many stacked rows we used on each side (base matches `my-16`).
    const maxTopDepth = placements.reduce((m, p) => (p.isTop ? Math.max(m, p.depth) : m), 0)
    const maxBottomDepth = placements.reduce((m, p) => (!p.isTop ? Math.max(m, p.depth) : m), 0)

    return (
        <div
            ref={containerRef}
            className="relative h-2 bg-border-light"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                marginTop: `calc(4rem + ${maxTopDepth * rowHeight}px)`,
                marginBottom: `calc(4rem + ${maxBottomDepth * rowHeight}px)`,
            }}
        >
            {sortedItems.map((item, i) => (
                <BillingGaugeItem
                    key={i}
                    item={item}
                    maxValue={maxValue}
                    isWithinUsageLimit={isWithinUsageLimit}
                    placement={placements[i] ?? { isTop: i % 2 !== 0, depth: 0 }}
                    rowHeight={rowHeight}
                    product={product}
                    valueFormatter={valueFormatter}
                />
            ))}
        </div>
    )
}
