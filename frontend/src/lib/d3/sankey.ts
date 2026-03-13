/**
 * Reimplementation of d3-sankey (https://github.com/d3/d3-sankey/tree/master/src)
 * Replaces the outdated d3-sankey npm package.
 */

import { Link, linkHorizontal } from 'd3'
import { max, min, sum } from 'd3'

// ---- Public types ----

export type SankeyLink<N, L> = L & {
    source: N
    target: N
    value: number
    y0: number
    y1: number
    width: number
    index: number
}

export interface SankeyLayout<Data, N, L> {
    (data: Data): { nodes: N[]; links: SankeyLink<N, L>[] }
    nodeId(fn: (node: N) => string | number): this
    nodeAlign(fn: (node: N, n: number) => number): this
    nodeSort(compare: ((a: N, b: N) => number) | null | undefined): this
    nodeWidth(width: number): this
    nodePadding(padding: number): this
    size(size: [number, number]): this
    extent(extent: [[number, number], [number, number]]): this
}

// ---- Internal computation types ----
// These represent the fully-resolved state used during layout computation.

interface InternalNode {
    index: number
    depth: number
    height: number
    layer: number
    value: number
    x0: number
    x1: number
    y0: number
    y1: number
    sourceLinks: InternalLink[]
    targetLinks: InternalLink[]
}

interface InternalLink {
    index: number
    source: InternalNode
    target: InternalNode
    value: number
    width: number
    y0: number
    y1: number
}

// Links before computeNodeLinks resolves source/target from IDs to node objects
type InputLink = Omit<InternalLink, 'source' | 'target' | 'width' | 'y0' | 'y1'> & {
    source: string | number | InternalNode
    target: string | number | InternalNode
    width?: number
    y0?: number
    y1?: number
}

// ---- Alignment functions ----

export function sankeyLeft(node: { depth: number }): number {
    return node.depth
}

export function sankeyJustify(node: { depth: number; sourceLinks: unknown[] }, n: number): number {
    return node.sourceLinks.length ? node.depth : n - 1
}

// ---- Link path generator ----

function horizontalSource(d: InternalLink): [number, number] {
    return [d.source.x1, d.y0]
}

function horizontalTarget(d: InternalLink): [number, number] {
    return [d.target.x0, d.y1]
}

export function sankeyLinkHorizontal<N = unknown, L = unknown>(): Link<any, SankeyLink<N, L>, [number, number]> {
    return linkHorizontal<InternalLink, [number, number]>()
        .source(horizontalSource)
        .target(horizontalTarget) as unknown as Link<any, SankeyLink<N, L>, [number, number]>
}

// ---- Helpers ----

function ascendingBreadth(a: { y0: number }, b: { y0: number }): number {
    return a.y0 - b.y0
}

function ascendingSourceBreadth(a: InternalLink, b: InternalLink): number {
    return ascendingBreadth(a.source, b.source) || a.index - b.index
}

function ascendingTargetBreadth(a: InternalLink, b: InternalLink): number {
    return ascendingBreadth(a.target, b.target) || a.index - b.index
}

function nodeValue(d: { value: number }): number {
    return d.value
}

function find(nodeById: Map<string | number, InternalNode>, id: string | number): InternalNode {
    const node = nodeById.get(id)
    if (!node) {
        throw new Error('missing: ' + id)
    }
    return node
}

function computeLinkBreadths({ nodes }: { nodes: InternalNode[] }): void {
    for (const node of nodes) {
        let y0 = node.y0
        let y1 = y0
        for (const link of node.sourceLinks) {
            link.y0 = y0 + link.width / 2
            y0 += link.width
        }
        for (const link of node.targetLinks) {
            link.y1 = y1 + link.width / 2
            y1 += link.width
        }
    }
}

// ---- Main sankey factory ----

export default function sankey<Data = any, N = any, L = any>(): SankeyLayout<Data, N, L> {
    let x0 = 0,
        y0 = 0,
        x1 = 1,
        y1 = 1
    let dx = 24
    let dy = 8,
        py = 8
    let id: (d: InternalNode) => string | number = (d) => d.index
    let align: (node: InternalNode, n: number) => number = sankeyJustify as unknown as (
        node: InternalNode,
        n: number
    ) => number
    let sort: ((a: InternalNode, b: InternalNode) => number) | null | undefined

    function sankeyLayout(data: any): any {
        const graph = { nodes: data.nodes as InternalNode[], links: data.links as InputLink[] }
        computeNodeLinks(graph)
        computeNodeValues(graph)
        computeNodeDepths(graph)
        computeNodeHeights(graph)
        computeNodeBreadths(graph)
        computeLinkBreadths(graph)
        return graph
    }

    sankeyLayout.nodeId = function (fn: (node: N) => string | number): any {
        id = fn as unknown as (d: InternalNode) => string | number
        return sankeyLayout
    }

    sankeyLayout.nodeAlign = function (fn: (node: N, n: number) => number): any {
        align = fn as unknown as (node: InternalNode, n: number) => number
        return sankeyLayout
    }

    sankeyLayout.nodeSort = function (compare: ((a: N, b: N) => number) | null | undefined): any {
        sort = compare as unknown as ((a: InternalNode, b: InternalNode) => number) | null | undefined
        return sankeyLayout
    }

    sankeyLayout.nodeWidth = function (width: number): any {
        dx = width
        return sankeyLayout
    }

    sankeyLayout.nodePadding = function (padding: number): any {
        dy = py = padding
        return sankeyLayout
    }

    sankeyLayout.size = function ([width, height]: [number, number]): any {
        x0 = y0 = 0
        x1 = width
        y1 = height
        return sankeyLayout
    }

    sankeyLayout.extent = function ([[left, top], [right, bottom]]: [[number, number], [number, number]]): any {
        x0 = left
        y0 = top
        x1 = right
        y1 = bottom
        return sankeyLayout
    }

    function computeNodeLinks({
        nodes: nodeList,
        links: linkList,
    }: {
        nodes: InternalNode[]
        links: InputLink[]
    }): void {
        for (const [i, node] of nodeList.entries()) {
            node.index = i
            node.sourceLinks = []
            node.targetLinks = []
        }
        const nodeById = new Map(nodeList.map((d) => [id(d), d]))
        for (const [i, link] of linkList.entries()) {
            link.index = i
            if (typeof link.source !== 'object') {
                link.source = find(nodeById, link.source)
            }
            if (typeof link.target !== 'object') {
                link.target = find(nodeById, link.target)
            }
            ;(link.source as InternalNode).sourceLinks.push(link as InternalLink)
            ;(link.target as InternalNode).targetLinks.push(link as InternalLink)
        }
    }

    function computeNodeValues({ nodes: nodeList }: { nodes: InternalNode[] }): void {
        for (const node of nodeList) {
            node.value = Math.max(sum(node.sourceLinks, nodeValue), sum(node.targetLinks, nodeValue))
        }
    }

    function computeNodeDepths({ nodes: nodeList }: { nodes: InternalNode[] }): void {
        const n = nodeList.length
        let current = new Set(nodeList)
        let next = new Set<InternalNode>()
        let x = 0
        while (current.size) {
            for (const node of current) {
                node.depth = x
                for (const { target } of node.sourceLinks) {
                    next.add(target)
                }
            }
            if (++x > n) {
                throw new Error('circular link')
            }
            current = next
            next = new Set()
        }
    }

    function computeNodeHeights({ nodes: nodeList }: { nodes: InternalNode[] }): void {
        const n = nodeList.length
        let current = new Set(nodeList)
        let next = new Set<InternalNode>()
        let x = 0
        while (current.size) {
            for (const node of current) {
                node.height = x
                for (const { source } of node.targetLinks) {
                    next.add(source)
                }
            }
            if (++x > n) {
                throw new Error('circular link')
            }
            current = next
            next = new Set()
        }
    }

    function computeNodeLayers({ nodes: nodeList }: { nodes: InternalNode[] }): InternalNode[][] {
        const x = max(nodeList, (d) => d.depth)! + 1
        const kx = (x1 - x0 - dx) / (x - 1)
        const columns: InternalNode[][] = new Array(x)
        for (const node of nodeList) {
            const i = Math.max(0, Math.min(x - 1, Math.floor(align(node, x))))
            node.layer = i
            node.x0 = x0 + i * kx
            node.x1 = node.x0 + dx
            if (columns[i]) {
                columns[i].push(node)
            } else {
                columns[i] = [node]
            }
        }
        if (sort) {
            for (const column of columns) {
                column.sort(sort)
            }
        }
        return columns
    }

    function initializeNodeBreadths(columns: InternalNode[][]): void {
        const ky = min(columns, (c) => (y1 - y0 - (c.length - 1) * py) / sum(c, nodeValue))!
        for (const columnNodes of columns) {
            let y = y0
            for (const node of columnNodes) {
                node.y0 = y
                node.y1 = y + node.value * ky
                y = node.y1 + py
                for (const link of node.sourceLinks) {
                    link.width = link.value * ky
                }
            }
            y = (y1 - y + py) / (columnNodes.length + 1)
            for (let i = 0; i < columnNodes.length; ++i) {
                const node = columnNodes[i]
                node.y0 += y * (i + 1)
                node.y1 += y * (i + 1)
            }
            reorderLinks(columnNodes)
        }
    }

    function computeNodeBreadths(graph: { nodes: InternalNode[] }): void {
        const columns = computeNodeLayers(graph)
        py = Math.min(dy, (y1 - y0) / (max(columns, (c) => c.length)! - 1))
        initializeNodeBreadths(columns)
        for (let i = 0; i < 6; ++i) {
            const alpha = Math.pow(0.99, i)
            const beta = Math.max(1 - alpha, (i + 1) / 6)
            relaxRightToLeft(columns, alpha, beta)
            relaxLeftToRight(columns, alpha, beta)
        }
    }

    function relaxLeftToRight(columns: InternalNode[][], alpha: number, beta: number): void {
        for (let i = 1, n = columns.length; i < n; ++i) {
            const column = columns[i]
            for (const target of column) {
                let y = 0
                let w = 0
                for (const { source, value } of target.targetLinks) {
                    const v = value * (target.layer - source.layer)
                    y += targetTop(source, target) * v
                    w += v
                }
                if (!(w > 0)) {
                    continue
                }
                const dy = (y / w - target.y0) * alpha
                target.y0 += dy
                target.y1 += dy
                reorderNodeLinks(target)
            }
            if (sort === undefined) {
                column.sort(ascendingBreadth)
            }
            resolveCollisions(column, beta)
        }
    }

    function relaxRightToLeft(columns: InternalNode[][], alpha: number, beta: number): void {
        for (let n = columns.length, i = n - 2; i >= 0; --i) {
            const column = columns[i]
            for (const source of column) {
                let y = 0
                let w = 0
                for (const { target, value } of source.sourceLinks) {
                    const v = value * (target.layer - source.layer)
                    y += sourceTop(source, target) * v
                    w += v
                }
                if (!(w > 0)) {
                    continue
                }
                const dy = (y / w - source.y0) * alpha
                source.y0 += dy
                source.y1 += dy
                reorderNodeLinks(source)
            }
            if (sort === undefined) {
                column.sort(ascendingBreadth)
            }
            resolveCollisions(column, beta)
        }
    }

    function resolveCollisions(nodeList: InternalNode[], alpha: number): void {
        const i = nodeList.length >> 1
        const subject = nodeList[i]
        resolveCollisionsBottomToTop(nodeList, subject.y0 - py, i - 1, alpha)
        resolveCollisionsTopToBottom(nodeList, subject.y1 + py, i + 1, alpha)
        resolveCollisionsBottomToTop(nodeList, y1, nodeList.length - 1, alpha)
        resolveCollisionsTopToBottom(nodeList, y0, 0, alpha)
    }

    function resolveCollisionsTopToBottom(nodeList: InternalNode[], y: number, i: number, alpha: number): void {
        for (; i < nodeList.length; ++i) {
            const node = nodeList[i]
            const dy = (y - node.y0) * alpha
            if (dy > 1e-6) {
                node.y0 += dy
                node.y1 += dy
            }
            y = node.y1 + py
        }
    }

    function resolveCollisionsBottomToTop(nodeList: InternalNode[], y: number, i: number, alpha: number): void {
        for (; i >= 0; --i) {
            const node = nodeList[i]
            const dy = (node.y1 - y) * alpha
            if (dy > 1e-6) {
                node.y0 -= dy
                node.y1 -= dy
            }
            y = node.y0 - py
        }
    }

    function reorderNodeLinks({ sourceLinks, targetLinks }: InternalNode): void {
        for (const { source } of targetLinks) {
            source.sourceLinks.sort(ascendingTargetBreadth)
        }
        for (const { target } of sourceLinks) {
            target.targetLinks.sort(ascendingSourceBreadth)
        }
    }

    function reorderLinks(nodeList: InternalNode[]): void {
        for (const { sourceLinks, targetLinks } of nodeList) {
            sourceLinks.sort(ascendingTargetBreadth)
            targetLinks.sort(ascendingSourceBreadth)
        }
    }

    // Returns the target.y0 that would produce an ideal link from source to target.
    function targetTop(source: InternalNode, target: InternalNode): number {
        let y = source.y0 - ((source.sourceLinks.length - 1) * py) / 2
        for (const { target: node, width } of source.sourceLinks) {
            if (node === target) {
                break
            }
            y += width + py
        }
        for (const { source: node, width } of target.targetLinks) {
            if (node === source) {
                break
            }
            y -= width
        }
        return y
    }

    // Returns the source.y0 that would produce an ideal link from source to target.
    function sourceTop(source: InternalNode, target: InternalNode): number {
        let y = target.y0 - ((target.targetLinks.length - 1) * py) / 2
        for (const { source: node, width } of target.targetLinks) {
            if (node === source) {
                break
            }
            y += width + py
        }
        for (const { target: node, width } of source.sourceLinks) {
            if (node === target) {
                break
            }
            y -= width
        }
        return y
    }

    return sankeyLayout as any
}
