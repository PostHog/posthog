import { useMemo } from 'react'

import { mergeTheme } from '../theme'
import type { PathsProps } from '../types'

/**
 * A Sankey-like paths visualization.
 *
 * Renders an SVG diagram showing user flow between nodes. Nodes are laid out
 * in columns (depth levels) and links are drawn as curved bands between them.
 */
export function Paths(props: PathsProps): JSX.Element {
    const { nodes, links, maxPaths = 50 } = props
    const theme = mergeTheme(props.theme)

    const layout = useMemo(() => computeLayout(nodes, links, maxPaths), [nodes, links, maxPaths])

    const width = typeof props.width === 'number' ? props.width : 800
    const height = typeof props.height === 'number' ? props.height : 400

    if (layout.columns.length === 0) {
        return <div className={props.className}>No path data</div>
    }

    const colWidth = width / layout.columns.length
    const nodeWidth = 16
    const nodePadding = 8

    return (
        <div className={props.className} role="figure" aria-label={props.ariaLabel ?? 'Paths'}>
            <svg width={width} height={height} style={{ fontFamily: theme.fontFamily, fontSize: theme.fontSize }}>
                {/* Links */}
                {layout.linkPositions.map((link, i) => (
                    <path
                        key={i}
                        d={sankeyLinkPath(link, colWidth, nodeWidth)}
                        fill="none"
                        stroke={theme.colors[link.sourceCol % theme.colors.length]}
                        strokeWidth={Math.max(1, link.width)}
                        strokeOpacity={0.3}
                    >
                        <title>
                            {link.source} → {link.target}: {link.value}
                        </title>
                    </path>
                ))}
                {/* Nodes */}
                {layout.nodePositions.map((node) => (
                    <g key={node.name} transform={`translate(${node.x}, ${node.y})`}>
                        <rect
                            width={nodeWidth}
                            height={Math.max(node.height, 2)}
                            fill={theme.colors[node.col % theme.colors.length]}
                            rx={2}
                        />
                        <text
                            x={nodeWidth + 6}
                            y={Math.max(node.height, 2) / 2}
                            dominantBaseline="middle"
                            fill={theme.axisColor}
                            fontSize={(theme.fontSize ?? 12) - 1}
                        >
                            {node.name}
                        </text>
                    </g>
                ))}
            </svg>
        </div>
    )
}

// ---------------------------------------------------------------------------
// Layout computation (simplified Sankey)
// ---------------------------------------------------------------------------

interface NodePosition {
    name: string
    col: number
    x: number
    y: number
    height: number
    value: number
}

interface LinkPosition {
    source: string
    target: string
    sourceCol: number
    sourceY: number
    targetY: number
    width: number
    value: number
}

interface Layout {
    columns: string[][]
    nodePositions: NodePosition[]
    linkPositions: LinkPosition[]
}

function computeLayout(
    nodes: { name: string; count: number }[],
    links: { source: string; target: string; value: number }[],
    maxPaths: number
): Layout {
    // Assign depths by BFS from root nodes
    const outgoing = new Map<string, { target: string; value: number }[]>()
    const incoming = new Map<string, Set<string>>()

    const sortedLinks = [...links].sort((a, b) => b.value - a.value).slice(0, maxPaths)

    for (const link of sortedLinks) {
        if (!outgoing.has(link.source)) {
            outgoing.set(link.source, [])
        }
        outgoing.get(link.source)!.push(link)
        if (!incoming.has(link.target)) {
            incoming.set(link.target, new Set())
        }
        incoming.get(link.target)!.add(link.source)
    }

    const allNames = new Set([...sortedLinks.map((l) => l.source), ...sortedLinks.map((l) => l.target)])
    const roots = [...allNames].filter((n) => !incoming.has(n) || incoming.get(n)!.size === 0)
    if (roots.length === 0 && allNames.size > 0) {
        roots.push([...allNames][0])
    }

    const depth = new Map<string, number>()
    const queue = [...roots]
    for (const r of roots) {
        depth.set(r, 0)
    }
    while (queue.length > 0) {
        const current = queue.shift()!
        const d = depth.get(current)!
        for (const link of outgoing.get(current) ?? []) {
            if (!depth.has(link.target)) {
                depth.set(link.target, d + 1)
                queue.push(link.target)
            }
        }
    }

    const maxDepth = Math.max(0, ...depth.values())
    const columns: string[][] = Array.from({ length: maxDepth + 1 }, () => [])
    for (const [name, d] of depth) {
        columns[d].push(name)
    }

    // Build node value map
    const nodeValues = new Map<string, number>()
    for (const n of nodes) {
        nodeValues.set(n.name, n.count)
    }

    // Position nodes
    const chartHeight = 400
    const nodePositions: NodePosition[] = []
    const nodeMap = new Map<string, NodePosition>()

    for (let col = 0; col < columns.length; col++) {
        const colNodes = columns[col]
        const totalValue = colNodes.reduce((sum, n) => sum + (nodeValues.get(n) ?? 1), 0)
        let y = 0
        for (const name of colNodes) {
            const value = nodeValues.get(name) ?? 1
            const h = totalValue > 0 ? (value / totalValue) * (chartHeight - colNodes.length * 8) : 20
            const pos: NodePosition = { name, col, x: col * (800 / Math.max(columns.length, 1)), y, height: h, value }
            nodePositions.push(pos)
            nodeMap.set(name, pos)
            y += h + 8
        }
    }

    // Position links
    const linkPositions: LinkPosition[] = []
    const sourceYOffset = new Map<string, number>()
    const targetYOffset = new Map<string, number>()

    for (const link of sortedLinks) {
        const sn = nodeMap.get(link.source)
        const tn = nodeMap.get(link.target)
        if (!sn || !tn) {
            continue
        }
        const w = sn.value > 0 ? (link.value / sn.value) * sn.height : 2
        const sy = sn.y + (sourceYOffset.get(link.source) ?? 0)
        const ty = tn.y + (targetYOffset.get(link.target) ?? 0)
        sourceYOffset.set(link.source, (sourceYOffset.get(link.source) ?? 0) + w)
        targetYOffset.set(link.target, (targetYOffset.get(link.target) ?? 0) + w)

        linkPositions.push({
            source: link.source,
            target: link.target,
            sourceCol: sn.col,
            sourceY: sy + w / 2,
            targetY: ty + w / 2,
            width: w,
            value: link.value,
        })
    }

    return { columns, nodePositions, linkPositions }
}

function sankeyLinkPath(link: LinkPosition, colWidth: number, nodeWidth: number): string {
    const x0 = link.sourceCol * colWidth + nodeWidth
    const x1 = (link.sourceCol + 1) * colWidth
    const midX = (x0 + x1) / 2
    return `M ${x0},${link.sourceY} C ${midX},${link.sourceY} ${midX},${link.targetY} ${x1},${link.targetY}`
}
