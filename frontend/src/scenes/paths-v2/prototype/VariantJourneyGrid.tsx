/**
 * PROTOTYPE (throwaway branch, do not merge).
 * Variant A "Journey grid": fixed-height node cards in step columns, curved ribbons between
 * them, drop-offs as quiet fade-out stubs (no red), expandable "other" card per column.
 */
import { useMemo, useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyDuration } from 'lib/utils/durations'

import {
    RowColumnModel,
    RowEdge,
    RowNode,
    formatPercentage,
    middleEllipsis,
    ribbonPath,
    shortPathName,
} from './rowColumnModel'

const CARD_W = 224
const GAP_W = 104
const CARD_H = 64
const ROW_GAP = 16
const HEADER_H = 28
const MEMBER_ROW_H = 22
const MAX_MEMBERS_SHOWN = 8
const MAX_RIBBON_T = 40
const STUB_W = 48

interface CardGeometry {
    node: RowNode
    x: number
    y: number
    height: number
}

interface PortedEdge {
    edge: RowEdge
    thickness: number
    fromX: number
    fromY: number
    toX: number
    toY: number
}

export function VariantJourneyGrid({
    model,
    showPercentages,
    nodeColor,
}: {
    model: RowColumnModel
    showPercentages: boolean
    nodeColor: string
}): JSX.Element {
    const [expandedColumns, setExpandedColumns] = useState<Record<number, boolean>>({})

    const { cards, ports, stubs, chartWidth, chartHeight } = useMemo(() => {
        const cards = new Map<string, CardGeometry>()
        model.columns.forEach((column, columnIndex) => {
            let y = HEADER_H
            for (const node of column) {
                const expanded = node.isOther && expandedColumns[columnIndex]
                const height = expanded
                    ? CARD_H + Math.min(node.members.length, MAX_MEMBERS_SHOWN) * MEMBER_ROW_H + 8
                    : CARD_H
                cards.set(node.key, { node, x: columnIndex * (CARD_W + GAP_W), y, height })
                y += height + ROW_GAP
            }
        })

        const thicknessFor = (value: number): number =>
            Math.max(2, (value / Math.max(model.maxEdgeValue, 1)) * MAX_RIBBON_T)

        // stack ports per card side, ordered by the connected card's vertical position
        const outCursor = new Map<string, number>()
        const inCursor = new Map<string, number>()
        const sortedEdges = [...model.edges].sort(
            (a, b) =>
                (cards.get(a.from)?.y ?? 0) - (cards.get(b.from)?.y ?? 0) ||
                (cards.get(a.to)?.y ?? 0) - (cards.get(b.to)?.y ?? 0)
        )
        const ports: PortedEdge[] = []
        for (const edge of sortedEdges) {
            const from = cards.get(edge.from)
            const to = cards.get(edge.to)
            if (!from || !to) {
                continue
            }
            const thickness = thicknessFor(edge.value)
            const fromY = from.y + 8 + (outCursor.get(edge.from) ?? 0)
            const toY = to.y + 8 + (inCursor.get(edge.to) ?? 0)
            outCursor.set(edge.from, (outCursor.get(edge.from) ?? 0) + thickness + 2)
            inCursor.set(edge.to, (inCursor.get(edge.to) ?? 0) + thickness + 2)
            ports.push({ edge, thickness, fromX: from.x + CARD_W, fromY, toX: to.x, toY })
        }

        // drop-off stubs continue after the outgoing ports; hidden on the last visible column
        const lastColumn = model.columns.length - 1
        const stubs = Array.from(cards.values())
            .filter(({ node }) => node.dropoff > 0 && node.step < lastColumn)
            .map(({ node, x, y }) => ({
                node,
                thickness: thicknessFor(node.dropoff),
                x: x + CARD_W,
                y: y + 8 + (outCursor.get(node.key) ?? 0),
            }))

        const chartWidth = model.columns.length * (CARD_W + GAP_W) - GAP_W + STUB_W
        const chartHeight = Math.max(...Array.from(cards.values()).map((c) => c.y + c.height), 0) + 24
        return { cards, ports, stubs, chartWidth, chartHeight }
    }, [model, expandedColumns])

    return (
        <div className="relative overflow-auto pb-2">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="relative" style={{ width: chartWidth, height: chartHeight }}>
                <svg width={chartWidth} height={chartHeight} className="absolute inset-0 pointer-events-none">
                    <defs>
                        <linearGradient id="proto-dropoff-fade" x1="0" y1="0" x2="1" y2="0">
                            <stop offset="0%" stopColor="var(--text-secondary)" stopOpacity="0.35" />
                            <stop offset="100%" stopColor="var(--text-secondary)" stopOpacity="0" />
                        </linearGradient>
                    </defs>
                    {ports.map(({ edge, thickness, fromX, fromY, toX, toY }) => {
                        const fromNode = cards.get(edge.from)?.node
                        return (
                            <path
                                key={`${edge.from}→${edge.to}`}
                                d={ribbonPath(fromX, fromY, thickness, toX, toY, thickness)}
                                fill={nodeColor}
                                opacity={0.14}
                                className="pointer-events-auto hover:opacity-40 transition-opacity"
                            >
                                <title>
                                    {`${shortPathName(cards.get(edge.from)?.node.name ?? '')} → ${shortPathName(
                                        cards.get(edge.to)?.node.name ?? ''
                                    )}: ${edge.value} users${
                                        fromNode ? ` (${formatPercentage(edge.value, fromNode.count)} of node)` : ''
                                    }${edge.avgTime != null ? `, avg ${humanFriendlyDuration(edge.avgTime)}` : ''}`}
                                </title>
                            </path>
                        )
                    })}
                    {stubs.map(({ node, thickness, x, y }) => (
                        <path
                            key={`stub-${node.key}`}
                            d={`M ${x},${y} L ${x + STUB_W},${y + thickness * 0.25} L ${x + STUB_W},${
                                y + thickness * 0.75
                            } L ${x},${y + thickness} Z`}
                            fill="url(#proto-dropoff-fade)"
                            className="pointer-events-auto"
                        >
                            <title>{`${node.dropoff} users end their journey here (${formatPercentage(
                                node.dropoff,
                                node.count
                            )} of node)`}</title>
                        </path>
                    ))}
                </svg>

                {model.columns.map((_, columnIndex) => (
                    <div
                        key={`header-${columnIndex}`}
                        className="absolute text-xs font-semibold text-secondary"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ left: columnIndex * (CARD_W + GAP_W), top: 0, width: CARD_W }}
                    >
                        Step {columnIndex + 1}
                    </div>
                ))}

                {Array.from(cards.values()).map(({ node, x, y, height }) => {
                    const displayName = node.isOther ? node.name : shortPathName(node.name)
                    const expanded = node.isOther && expandedColumns[node.step]
                    return (
                        <div
                            key={node.key}
                            className={`absolute rounded border bg-surface-primary px-2 py-1.5 ${
                                node.isOther ? 'border-dashed cursor-pointer hover:border-primary' : ''
                            }`}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ left: x, top: y, width: CARD_W, height }}
                            onClick={
                                node.isOther
                                    ? () => setExpandedColumns((prev) => ({ ...prev, [node.step]: !prev[node.step] }))
                                    : undefined
                            }
                        >
                            <Tooltip title={node.isOther ? `${node.members.length} more path items` : node.name}>
                                <div className="text-xs font-semibold truncate">
                                    {node.isOther
                                        ? `${displayName} (${node.members.length} path items)${expanded ? '' : ' ▸'}`
                                        : middleEllipsis(displayName, 32)}
                                </div>
                            </Tooltip>
                            <div className="flex items-baseline gap-1.5 mt-0.5">
                                <span className="text-sm font-semibold">{node.count}</span>
                                {showPercentages && (
                                    <span className="text-xs text-secondary">
                                        {formatPercentage(node.count, model.startTotal)} of start
                                    </span>
                                )}
                            </div>
                            <div className="h-1 rounded-full bg-fill-secondary mt-1">
                                <div
                                    className="h-1 rounded-full"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{
                                        width: `${Math.max(
                                            3,
                                            (node.count / Math.max(model.stepTotals[node.step], 1)) * 100
                                        )}%`,
                                        backgroundColor: node.isOther ? 'var(--text-secondary)' : nodeColor,
                                    }}
                                />
                            </div>
                            {expanded && (
                                <div className="mt-1.5 border-t pt-1">
                                    {node.members.slice(0, MAX_MEMBERS_SHOWN).map((member) => (
                                        <div
                                            key={member.name}
                                            className="flex justify-between text-xs text-secondary leading-[22px]"
                                        >
                                            <span className="truncate pr-2">
                                                {middleEllipsis(shortPathName(member.name), 26)}
                                            </span>
                                            <span>{member.count}</span>
                                        </div>
                                    ))}
                                    {node.members.length > MAX_MEMBERS_SHOWN && (
                                        <div className="text-xs text-secondary leading-[22px]">
                                            and {node.members.length - MAX_MEMBERS_SHOWN} more
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
