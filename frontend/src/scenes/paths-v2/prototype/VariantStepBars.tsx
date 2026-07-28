/**
 * PROTOTYPE (throwaway branch, do not merge).
 * Variant B "Step bars": each step is a funnel-style stacked bar, rows are segments with the
 * same color for the same path item across steps. No permanent ribbons: hovering a segment
 * draws its connections to the neighboring steps. Drop-off is the shrinking bar, annotated
 * in the gap between steps.
 */
import { useMemo, useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'

import { RowColumnModel, RowNode, formatPercentage, middleEllipsis, shortPathName } from './rowColumnModel'

const BAR_H = 420
const BAR_W = 64
const LABEL_W = 168
const PITCH = BAR_W + LABEL_W + 48
const TOP_PAD = 40

function colorForName(name: string, isOther: boolean): string {
    if (isOther) {
        return 'var(--text-secondary)'
    }
    let hash = 5381
    for (let i = 0; i < name.length; i++) {
        hash = (hash * 33) ^ name.charCodeAt(i)
    }
    return getSeriesColor(Math.abs(hash) % 15)
}

interface SegmentGeometry {
    node: RowNode
    x: number
    y: number
    height: number
}

export function VariantStepBars({
    model,
    showPercentages,
}: {
    model: RowColumnModel
    showPercentages: boolean
}): JSX.Element {
    const [hoveredKey, setHoveredKey] = useState<string | null>(null)

    const { segments, chartWidth, chartHeight } = useMemo(() => {
        const segments = new Map<string, SegmentGeometry>()
        model.columns.forEach((column, columnIndex) => {
            const stepTotal = Math.max(model.stepTotals[columnIndex], 1)
            const barHeight = (model.stepTotals[columnIndex] / Math.max(model.maxStepTotal, 1)) * BAR_H
            let y = TOP_PAD
            for (const node of column) {
                const height = Math.max(3, (node.count / stepTotal) * barHeight)
                segments.set(node.key, { node, x: columnIndex * PITCH, y, height })
                y += height + 2
            }
        })
        return {
            segments,
            chartWidth: model.columns.length * PITCH - LABEL_W / 2,
            chartHeight: TOP_PAD + BAR_H + 32,
        }
    }, [model])

    const hoverEdges = useMemo(() => {
        if (!hoveredKey) {
            return []
        }
        return model.edges.filter((edge) => edge.from === hoveredKey || edge.to === hoveredKey)
    }, [model, hoveredKey])

    const connectedKeys = useMemo(() => {
        const keys = new Set<string>()
        if (hoveredKey) {
            keys.add(hoveredKey)
            for (const edge of hoverEdges) {
                keys.add(edge.from)
                keys.add(edge.to)
            }
        }
        return keys
    }, [hoveredKey, hoverEdges])

    return (
        <div className="relative overflow-auto pb-2">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="relative" style={{ width: chartWidth, height: chartHeight }}>
                {/* step headers and drop-off annotations */}
                {model.columns.map((_, columnIndex) => {
                    const dropped =
                        columnIndex > 0 ? model.stepTotals[columnIndex - 1] - model.stepTotals[columnIndex] : 0
                    return (
                        <div key={`header-${columnIndex}`}>
                            <div
                                className="absolute text-xs font-semibold text-secondary"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ left: columnIndex * PITCH, top: 0, width: BAR_W + LABEL_W }}
                            >
                                Step {columnIndex + 1} · {model.stepTotals[columnIndex]}
                                {showPercentages && columnIndex > 0 && (
                                    <span className="font-normal">
                                        {' '}
                                        ({formatPercentage(model.stepTotals[columnIndex], model.startTotal)} of start)
                                    </span>
                                )}
                            </div>
                            {dropped > 0 && (
                                <div
                                    className="absolute text-xs text-secondary"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ left: (columnIndex - 1) * PITCH + BAR_W + 8, top: 18, width: LABEL_W }}
                                >
                                    −{dropped} drop off
                                    {showPercentages &&
                                        ` (${formatPercentage(dropped, model.stepTotals[columnIndex - 1])})`}
                                </div>
                            )}
                        </div>
                    )
                })}

                {/* hover connections */}
                <svg width={chartWidth} height={chartHeight} className="absolute inset-0 pointer-events-none">
                    {hoverEdges.map((edge) => {
                        const from = segments.get(edge.from)
                        const to = segments.get(edge.to)
                        if (!from || !to) {
                            return null
                        }
                        const x0 = from.x + BAR_W
                        const y0 = from.y + from.height / 2
                        const x1 = to.x
                        const y1 = to.y + to.height / 2
                        const xm = (x0 + x1) / 2
                        return (
                            <path
                                key={`${edge.from}→${edge.to}`}
                                d={`M ${x0},${y0} C ${xm},${y0} ${xm},${y1} ${x1},${y1}`}
                                fill="none"
                                stroke="var(--text-primary)"
                                strokeWidth={Math.max(1.5, (edge.value / Math.max(model.maxEdgeValue, 1)) * 8)}
                                opacity={0.6}
                            />
                        )
                    })}
                </svg>

                {/* bars */}
                {Array.from(segments.values()).map(({ node, x, y, height }) => {
                    const displayName = node.isOther
                        ? `${node.name} (${node.members.length})`
                        : shortPathName(node.name)
                    const outgoing = model.edges
                        .filter((edge) => edge.from === node.key)
                        .sort((a, b) => b.value - a.value)
                    const dimmed = hoveredKey !== null && !connectedKeys.has(node.key)
                    return (
                        <div key={node.key}>
                            <Tooltip
                                title={
                                    <div className="deprecated-space-y-1">
                                        <div className="font-semibold">{node.isOther ? displayName : node.name}</div>
                                        <div>
                                            {node.count} users ({formatPercentage(node.count, model.startTotal)} of
                                            start)
                                        </div>
                                        {outgoing.slice(0, 5).map((edge) => (
                                            <div key={edge.to}>
                                                →{' '}
                                                {middleEllipsis(
                                                    shortPathName(segments.get(edge.to)?.node.name ?? ''),
                                                    24
                                                )}
                                                : {edge.value} ({formatPercentage(edge.value, node.count)})
                                            </div>
                                        ))}
                                        {node.dropoff > 0 && node.step < model.columns.length - 1 && (
                                            <div>
                                                ⏹ {node.dropoff} end here ({formatPercentage(node.dropoff, node.count)})
                                            </div>
                                        )}
                                    </div>
                                }
                            >
                                <div
                                    className="absolute rounded-sm cursor-pointer transition-opacity"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{
                                        left: x,
                                        top: y,
                                        width: BAR_W,
                                        height,
                                        backgroundColor: colorForName(node.name, node.isOther),
                                        opacity: dimmed ? 0.25 : node.isOther ? 0.5 : 0.85,
                                    }}
                                    onMouseEnter={() => setHoveredKey(node.key)}
                                    onMouseLeave={() => setHoveredKey(null)}
                                />
                            </Tooltip>
                            {height >= 14 && (
                                <div
                                    className={`absolute text-xs leading-tight transition-opacity ${
                                        dimmed ? 'opacity-25' : ''
                                    }`}
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ left: x + BAR_W + 8, top: y + height / 2 - 8, width: LABEL_W }}
                                >
                                    <div className="truncate font-medium">{middleEllipsis(displayName, 24)}</div>
                                    <div className="text-secondary">
                                        {node.count}
                                        {showPercentages &&
                                            ` · ${formatPercentage(node.count, model.stepTotals[node.step])}`}
                                    </div>
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
