/**
 * PROTOTYPE (throwaway branch, do not merge).
 * Variant C "Draft sankey": stays close to draft PR #29364 and v1 — value-scaled node rects,
 * an explicit drop-off node appended to each column, red drop-off ribbons like v1. Counts
 * only, "other" not expandable. The baseline to react against.
 */
import { useMemo } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { RowColumnModel, RowNode, formatPercentage, middleEllipsis, ribbonPath, shortPathName } from './rowColumnModel'

const NODE_W = 44
const PITCH = 264
const LABEL_H = 34
const COLUMN_H = 460
const TOP_PAD = 8

const DROPOFF_COLOR = 'rgba(220, 53, 69, 0.55)'

interface SankeyRect {
    node: RowNode | null // null = synthetic drop-off node
    key: string
    label: string
    count: number
    x: number
    y: number
    height: number
    isDropoff: boolean
}

interface SankeyRibbon {
    key: string
    path: string
    isDropoff: boolean
    title: string
}

export function VariantDraftSankey({ model, nodeColor }: { model: RowColumnModel; nodeColor: string }): JSX.Element {
    const { rects, ribbons, chartWidth, chartHeight } = useMemo(() => {
        const rects = new Map<string, SankeyRect>()

        // drop-off node in column c collects journeys that ended at column c-1 (draft behavior)
        const dropoffInto: number[] = model.columns.map((_, columnIndex) =>
            columnIndex === 0 ? 0 : model.columns[columnIndex - 1].reduce((sum, node) => sum + node.dropoff, 0)
        )

        const scale = (count: number): number =>
            Math.max(4, (count / Math.max(model.maxStepTotal, 1)) * (COLUMN_H - 5 * LABEL_H))

        model.columns.forEach((column, columnIndex) => {
            let y = TOP_PAD + LABEL_H
            for (const node of column) {
                const height = scale(node.count)
                rects.set(node.key, {
                    node,
                    key: node.key,
                    label: node.isOther ? `${node.name} (${node.members.length})` : shortPathName(node.name),
                    count: node.count,
                    x: columnIndex * PITCH,
                    y,
                    height,
                    isDropoff: false,
                })
                y += height + LABEL_H
            }
            if (dropoffInto[columnIndex] > 0) {
                const key = `${columnIndex}:$$dropoff$$`
                rects.set(key, {
                    node: null,
                    key,
                    label: 'Drop-off',
                    count: dropoffInto[columnIndex],
                    x: columnIndex * PITCH,
                    y,
                    height: scale(dropoffInto[columnIndex]),
                    isDropoff: true,
                })
            }
        })

        // sankey-style ports: outgoing ribbons parcel the node height by value share
        const outCursor = new Map<string, number>()
        const inCursor = new Map<string, number>()
        const takePort = (cursor: Map<string, number>, rect: SankeyRect, share: number): { y: number; t: number } => {
            const offset = cursor.get(rect.key) ?? 0
            const thickness = Math.max(1.5, rect.height * share)
            cursor.set(rect.key, offset + thickness)
            return { y: rect.y + offset, t: thickness }
        }

        const ribbons: SankeyRibbon[] = []
        const sortedEdges = [...model.edges].sort(
            (a, b) =>
                (rects.get(a.from)?.y ?? 0) - (rects.get(b.from)?.y ?? 0) ||
                (rects.get(a.to)?.y ?? 0) - (rects.get(b.to)?.y ?? 0)
        )
        for (const edge of sortedEdges) {
            const from = rects.get(edge.from)
            const to = rects.get(edge.to)
            if (!from || !to) {
                continue
            }
            const fromPort = takePort(outCursor, from, edge.value / Math.max(from.count, 1))
            const toPort = takePort(inCursor, to, edge.value / Math.max(to.count, 1))
            ribbons.push({
                key: `${edge.from}→${edge.to}`,
                path: ribbonPath(from.x + NODE_W, fromPort.y, fromPort.t, to.x, toPort.y, toPort.t),
                isDropoff: false,
                title: `${from.label} → ${to.label}: ${edge.value} users`,
            })
        }

        // red drop-off ribbons: from each node's remaining height into the next column's drop-off node
        model.columns.forEach((column, columnIndex) => {
            const dropoffRect = rects.get(`${columnIndex + 1}:$$dropoff$$`)
            if (!dropoffRect) {
                return
            }
            for (const node of column) {
                if (node.dropoff <= 0) {
                    continue
                }
                const from = rects.get(node.key)
                if (!from) {
                    continue
                }
                const fromPort = takePort(outCursor, from, node.dropoff / Math.max(node.count, 1))
                const toPort = takePort(inCursor, dropoffRect, node.dropoff / Math.max(dropoffRect.count, 1))
                ribbons.push({
                    key: `dropoff-${node.key}`,
                    path: ribbonPath(from.x + NODE_W, fromPort.y, fromPort.t, dropoffRect.x, toPort.y, toPort.t),
                    isDropoff: true,
                    title: `${from.label} → drop-off: ${node.dropoff} users (${formatPercentage(
                        node.dropoff,
                        node.count
                    )} of node)`,
                })
            }
        })

        return {
            rects,
            ribbons,
            chartWidth: model.columns.length * PITCH - PITCH + NODE_W + 220,
            chartHeight: COLUMN_H + TOP_PAD + LABEL_H,
        }
    }, [model])

    return (
        <div className="relative overflow-auto pb-2">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="relative" style={{ width: chartWidth, height: chartHeight }}>
                <svg width={chartWidth} height={chartHeight} className="absolute inset-0 pointer-events-none">
                    {ribbons.map((ribbon) => (
                        <path
                            key={ribbon.key}
                            d={ribbon.path}
                            fill={ribbon.isDropoff ? DROPOFF_COLOR : nodeColor}
                            opacity={ribbon.isDropoff ? 0.5 : 0.15}
                            className="pointer-events-auto hover:opacity-60 transition-opacity"
                        >
                            <title>{ribbon.title}</title>
                        </path>
                    ))}
                </svg>
                {Array.from(rects.values()).map((rect) => (
                    <div key={rect.key}>
                        <div
                            className="absolute text-xs leading-tight"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ left: rect.x, top: rect.y - LABEL_H + 4, width: 220 }}
                        >
                            <Tooltip title={rect.node?.name ?? rect.label}>
                                <div className="truncate font-medium">{middleEllipsis(rect.label, 30)}</div>
                            </Tooltip>
                            <div className="text-secondary">{rect.count}</div>
                        </div>
                        <div
                            className="absolute rounded-sm"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                left: rect.x,
                                top: rect.y,
                                width: NODE_W,
                                height: rect.height,
                                backgroundColor: rect.isDropoff
                                    ? 'var(--text-secondary)'
                                    : rect.node?.isOther
                                      ? 'var(--text-secondary)'
                                      : nodeColor,
                                opacity: rect.isDropoff ? 0.4 : rect.node?.isOther ? 0.6 : 1,
                            }}
                        />
                    </div>
                ))}
            </div>
        </div>
    )
}
