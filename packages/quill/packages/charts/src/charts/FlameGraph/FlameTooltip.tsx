/* eslint-disable react/forbid-dom-props -- the change color comes from the theme at runtime */
import React from 'react'

import { TooltipFooter, TooltipSurface, TooltipSwatch } from '../../overlays/TooltipSurface'
import { formatShare, type FlameInk } from './flame-colors'
import type { FlameChange, FlameNodeDatum, FlameTooltipContext } from './types'

function Row({ label, children }: { label: string; children: React.ReactNode }): React.ReactElement {
    return (
        <>
            <span className="opacity-70">{label}</span>
            <span className="tabular-nums text-right">{children}</span>
        </>
    )
}

function changeText(change: FlameChange): string | null {
    switch (change.kind) {
        case 'new':
            return 'New'
        case 'gone':
            return 'Gone'
        case 'low-sample':
            return 'Too few samples to compare'
        case 'none':
            return null
        default: {
            if (change.ratio === null) {
                return null
            }
            const percent = (change.ratio - 1) * 100
            const rounded = Math.abs(percent) >= 10 ? Math.round(percent) : Math.round(percent * 10) / 10
            return `${rounded > 0 ? '+' : rounded < 0 ? '−' : '±'}${Math.abs(rounded)}%`
        }
    }
}

function NodeRows<Meta>({
    node,
    format,
    comparing,
    ink,
}: {
    node: FlameNodeDatum<Meta>
    format: (value: number) => string
    comparing: boolean
    ink: FlameInk
}): React.ReactElement {
    const change = changeText(node.change)
    const changeColor =
        node.change.kind === 'slower' ? ink.slower : node.change.kind === 'faster' ? ink.faster : undefined
    return (
        <div className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
            <Row label="Total">
                {format(node.value)} <span className="opacity-70">({formatShare(node.fractionOfRoot)})</span>
            </Row>
            <Row label="Self">{format(node.self)}</Row>
            {node.depth > 0 ? <Row label="Of parent">{formatShare(node.fractionOfParent)}</Row> : null}
            {node.count !== undefined ? <Row label="Count">{node.count.toLocaleString()}</Row> : null}
            {comparing && node.baselineValue !== undefined ? (
                <Row label="Baseline">{format(node.baselineValue)}</Row>
            ) : null}
            {comparing && change ? (
                <Row label="Change">
                    <span className="font-semibold" style={{ color: changeColor }} data-attr="hog-chart-flame-change">
                        {change}
                    </span>
                </Row>
            ) : null}
        </div>
    )
}

export function FlameTooltip<Meta>({
    ctx,
    ink,
}: {
    ctx: FlameTooltipContext<Meta>
    ink: FlameInk
}): React.ReactElement {
    const { hit, valueFormatter, comparing } = ctx
    const color = ctx.seriesData[0]?.color
    if (hit.kind === 'bundle') {
        const { bundle } = hit
        const nested = bundle.descendantCount - bundle.count
        const whole = bundle.parent ? bundle.parent.value : ctx.totalValue
        return (
            <TooltipSurface data-attr="hog-chart-flame-tooltip">
                <div className="font-semibold mb-1">
                    {bundle.parent
                        ? `${bundle.count} smaller nodes in ${bundle.parent.name}`
                        : `${bundle.count} smaller roots`}
                </div>
                <div className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
                    <Row label="Total">
                        {valueFormatter(bundle.value)}{' '}
                        <span className="opacity-70">
                            ({formatShare(whole > 0 ? bundle.value / whole : 0)} of {bundle.parent ? 'parent' : 'total'}
                            )
                        </span>
                    </Row>
                    {nested > 0 ? <Row label="Nested nodes">{nested.toLocaleString()}</Row> : null}
                </div>
                {ctx.canFocus ? <TooltipFooter>Click to zoom in</TooltipFooter> : null}
            </TooltipSurface>
        )
    }
    const { node } = hit
    return (
        <TooltipSurface data-attr="hog-chart-flame-tooltip">
            <div className="flex items-start gap-2 mb-1">
                {color ? (
                    <span className="mt-1">
                        <TooltipSwatch color={color} />
                    </span>
                ) : null}
                <div className="min-w-0">
                    <div className="font-semibold break-all">{node.name}</div>
                    {node.group ? <div className="opacity-70 break-all">{node.group}</div> : null}
                </div>
            </div>
            <NodeRows node={node} format={valueFormatter} comparing={comparing} ink={ink} />
            {ctx.canFocus ? <TooltipFooter>Click to zoom in</TooltipFooter> : null}
        </TooltipSurface>
    )
}
