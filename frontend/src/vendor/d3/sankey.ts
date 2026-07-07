/**
 * Reimplementation of d3-sankey (https://github.com/d3/d3-sankey)
 * Original copyright  2015 Mike Bostock.
 *
 * The original code is over 7 years old and depends on an outdated
 * version of d3, so we shipped two versions of d3 to the client.
 * This reimplementation is more modern and only depends on newer
 * versions of the d3 modules we actually use.
 */

import { Link, linkHorizontal } from 'd3'
import { max, min, sum } from 'd3'

// ---- Public types ----

export interface SankeyExtraProperties {
    [key: string]: any
}

export type SankeyNode<N extends SankeyExtraProperties, L extends SankeyExtraProperties> = N & {
    sourceLinks: Array<SankeyLink<N, L>>
    targetLinks: Array<SankeyLink<N, L>>
    value: number
    fixedValue?: number
    index: number
    depth: number
    height: number
    layer: number
    x0: number
    x1: number
    y0: number
    y1: number
}

export type SankeyLink<N extends SankeyExtraProperties, L extends SankeyExtraProperties> = L & {
    source: SankeyNode<N, L>
    target: SankeyNode<N, L>
    value: number
    y0: number
    y1: number
    width: number
    index: number
}

export interface SankeyGraph<N extends SankeyExtraProperties, L extends SankeyExtraProperties> {
    nodes: Array<SankeyNode<N, L>>
    links: Array<SankeyLink<N, L>>
}

export type SankeyInputGraph = { nodes: any[]; links: any[] }

export interface SankeyLayout<N extends SankeyExtraProperties, L extends SankeyExtraProperties> {
    (graph: SankeyInputGraph): SankeyGraph<N, L>

    update(graph: SankeyGraph<N, L>): SankeyGraph<N, L>

    nodes(): (graph: SankeyInputGraph) => Array<SankeyNode<N, L>>
    nodes(nodes: Array<SankeyNode<N, L>>): this
    nodes(nodes: (graph: SankeyInputGraph) => Array<SankeyNode<N, L>>): this

    links(): (graph: SankeyInputGraph) => Array<SankeyLink<N, L>>
    links(links: Array<SankeyLink<N, L>>): this
    links(links: (graph: SankeyInputGraph) => Array<SankeyLink<N, L>>): this

    nodeId(): (node: SankeyNode<N, L>) => string | number
    nodeId(nodeId: (node: SankeyNode<N, L>) => string | number): this

    nodeAlign(): (node: SankeyNode<N, L>, n: number) => number
    nodeAlign(nodeAlign: (node: SankeyNode<N, L>, n: number) => number): this

    nodeWidth(): number
    nodeWidth(width: number): this

    nodePadding(): number
    nodePadding(padding: number): this

    extent(): [[number, number], [number, number]]
    extent(extent: [[number, number], [number, number]]): this

    size(): [number, number]
    size(size: [number, number]): this

    nodeSort(): ((a: SankeyNode<N, L>, b: SankeyNode<N, L>) => number) | undefined | null
    nodeSort(compare: ((a: SankeyNode<N, L>, b: SankeyNode<N, L>) => number) | undefined | null): this
}

// ---- Alignment functions ----

export function targetDepth(d: SankeyLink<{}, {}>): number {
    return d.target.depth
}

export function sankeyRight(node: SankeyNode<{}, {}>, n: number): number {
    return n - 1 - node.depth
}

export function sankeyLeft(node: SankeyNode<{}, {}>): number {
    return node.depth
}

export function sankeyJustify(node: SankeyNode<{}, {}>, n: number): number {
    return node.sourceLinks?.length ? node.depth : n - 1
}

export function sankeyCenter(node: SankeyNode<{}, {}>): number {
    return node.targetLinks?.length
        ? node.depth
        : node.sourceLinks?.length
          ? min(node.sourceLinks, targetDepth)! - 1
          : 0
}

// ---- Link path generator ----

function horizontalSource<N extends SankeyExtraProperties, L extends SankeyExtraProperties>(
    d: SankeyLink<N, L>
): [number, number] {
    return [d.source.x1, d.y0]
}

function horizontalTarget<N extends SankeyExtraProperties, L extends SankeyExtraProperties>(
    d: SankeyLink<N, L>
): [number, number] {
    return [d.target.x0, d.y1]
}

export function sankeyLinkHorizontal<N extends SankeyExtraProperties, L extends SankeyExtraProperties>(): Link<
    any,
    SankeyLink<N, L>,
    [number, number]
> {
    return linkHorizontal<SankeyLink<N, L>, [number, number]>().source(horizontalSource).target(horizontalTarget)
}

// ---- Helpers ----

function ascendingBreadth(a: { y0: number }, b: { y0: number }): number {
    return a.y0 - b.y0
}

function ascendingSourceBreadth(
    a: { source: { y0: number }; index: number },
    b: { source: { y0: number }; index: number }
): number {
    return ascendingBreadth(a.source, b.source) || a.index - b.index
}

function ascendingTargetBreadth(
    a: { target: { y0: number }; index: number },
    b: { target: { y0: number }; index: number }
): number {
    return ascendingBreadth(a.target, b.target) || a.index - b.index
}

function nodeValue(d: { value: number }): number {
    return d.value
}

function find<N extends SankeyExtraProperties, L extends SankeyExtraProperties>(
    nodeById: Map<string | number, SankeyNode<N, L>>,
    id: string | number
): SankeyNode<N, L> {
    const node = nodeById.get(id)
    if (!node) {
        throw new Error('missing: ' + id)
    }
    return node
}

function computeLinkBreadths<N extends SankeyExtraProperties, L extends SankeyExtraProperties>({
    nodes,
}: {
    nodes: SankeyNode<N, L>[]
}): void {
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

export default function sankey<
    N extends SankeyExtraProperties = any,
    L extends SankeyExtraProperties = any,
>(): SankeyLayout<N, L> {
    let x0 = 0,
        y0 = 0,
        x1 = 1,
        y1 = 1
    let dx = 24
    let dy = 8,
        py = 8

    let id: (d: SankeyNode<N, L>) => string | number = (d) => d.index
    let align: (node: SankeyNode<N, L>, n: number) => number = sankeyJustify
    let sort: ((a: SankeyNode<N, L>, b: SankeyNode<N, L>) => number) | null | undefined
    let nodesFn: (graph: SankeyInputGraph) => SankeyNode<N, L>[] = (graph) => graph.nodes
    let linksFn: (graph: SankeyInputGraph) => SankeyLink<N, L>[] = (graph) => graph.links

    let sankeyLayout: SankeyLayout<N, L>

    function layout(graph: SankeyInputGraph): SankeyGraph<N, L> {
        const g = { nodes: nodesFn(graph), links: linksFn(graph) }
        computeNodeLinks(g)
        computeNodeValues(g)
        computeNodeDepths(g)
        computeNodeHeights(g)
        computeNodeBreadths(g)
        computeLinkBreadths(g)
        return g
    }

    function update(graph: SankeyGraph<N, L>): SankeyGraph<N, L> {
        computeLinkBreadths({ nodes: graph.nodes })
        return graph
    }

    function nodesAccessor(): (graph: SankeyInputGraph) => SankeyNode<N, L>[]
    function nodesAccessor(fn: SankeyNode<N, L>[]): SankeyLayout<N, L>
    function nodesAccessor(fn: (graph: SankeyInputGraph) => SankeyNode<N, L>[]): SankeyLayout<N, L>
    function nodesAccessor(
        fn?: ((graph: SankeyInputGraph) => SankeyNode<N, L>[]) | SankeyNode<N, L>[]
    ): ((graph: SankeyInputGraph) => SankeyNode<N, L>[]) | SankeyLayout<N, L> {
        if (fn) {
            nodesFn = typeof fn === 'function' ? fn : () => fn
            return sankeyLayout
        }
        return nodesFn
    }

    function linksAccessor(): (graph: SankeyInputGraph) => SankeyLink<N, L>[]
    function linksAccessor(fn: SankeyLink<N, L>[]): SankeyLayout<N, L>
    function linksAccessor(fn: (graph: SankeyInputGraph) => SankeyLink<N, L>[]): SankeyLayout<N, L>
    function linksAccessor(
        fn?: ((graph: SankeyInputGraph) => SankeyLink<N, L>[]) | SankeyLink<N, L>[]
    ): ((graph: SankeyInputGraph) => SankeyLink<N, L>[]) | SankeyLayout<N, L> {
        if (fn) {
            linksFn = typeof fn === 'function' ? fn : () => fn
            return sankeyLayout
        }
        return linksFn
    }

    function nodeIdAccessor(): (node: SankeyNode<N, L>) => string | number
    function nodeIdAccessor(fn: (node: SankeyNode<N, L>) => string | number): SankeyLayout<N, L>
    function nodeIdAccessor(
        fn?: (node: SankeyNode<N, L>) => string | number
    ): ((node: SankeyNode<N, L>) => string | number) | SankeyLayout<N, L> {
        if (fn) {
            id = fn
            return sankeyLayout
        }
        return id
    }

    function nodeAlignAccessor(): (node: SankeyNode<N, L>, n: number) => number
    function nodeAlignAccessor(fn: (node: SankeyNode<N, L>, n: number) => number): SankeyLayout<N, L>
    function nodeAlignAccessor(
        fn?: (node: SankeyNode<N, L>, n: number) => number
    ): ((node: SankeyNode<N, L>, n: number) => number) | SankeyLayout<N, L> {
        if (fn) {
            align = fn
            return sankeyLayout
        }
        return align
    }

    function nodeSortAccessor(): ((a: SankeyNode<N, L>, b: SankeyNode<N, L>) => number) | undefined | null
    function nodeSortAccessor(
        fn: ((a: SankeyNode<N, L>, b: SankeyNode<N, L>) => number) | undefined | null
    ): SankeyLayout<N, L>
    function nodeSortAccessor(
        fn?: ((a: SankeyNode<N, L>, b: SankeyNode<N, L>) => number) | null | undefined
    ): ((a: SankeyNode<N, L>, b: SankeyNode<N, L>) => number) | undefined | null | SankeyLayout<N, L> {
        if (arguments.length) {
            sort = fn
            return sankeyLayout
        }
        return sort
    }

    function nodeWidthAccessor(): number
    function nodeWidthAccessor(width: number): SankeyLayout<N, L>
    function nodeWidthAccessor(width?: number): number | SankeyLayout<N, L> {
        if (width !== undefined) {
            dx = width
            return sankeyLayout
        }
        return dx
    }

    function nodePaddingAccessor(): number
    function nodePaddingAccessor(padding: number): SankeyLayout<N, L>
    function nodePaddingAccessor(padding?: number): number | SankeyLayout<N, L> {
        if (padding !== undefined) {
            dy = py = padding
            return sankeyLayout
        }
        return dy
    }

    function sizeAccessor(): [number, number]
    function sizeAccessor(size: [number, number]): SankeyLayout<N, L>
    function sizeAccessor(size?: [number, number]): [number, number] | SankeyLayout<N, L> {
        if (size) {
            x0 = y0 = 0
            x1 = size[0]
            y1 = size[1]
            return sankeyLayout
        }
        return [x1 - x0, y1 - y0]
    }

    function extentAccessor(): [[number, number], [number, number]]
    function extentAccessor(extent: [[number, number], [number, number]]): SankeyLayout<N, L>
    function extentAccessor(
        extent?: [[number, number], [number, number]]
    ): [[number, number], [number, number]] | SankeyLayout<N, L> {
        if (extent) {
            x0 = extent[0][0]
            y0 = extent[0][1]
            x1 = extent[1][0]
            y1 = extent[1][1]
            return sankeyLayout
        }
        return [
            [x0, y0],
            [x1, y1],
        ] satisfies [[number, number], [number, number]]
    }

    sankeyLayout = Object.assign(layout, {
        update,
        nodes: nodesAccessor,
        links: linksAccessor,
        nodeId: nodeIdAccessor,
        nodeAlign: nodeAlignAccessor,
        nodeSort: nodeSortAccessor,
        nodeWidth: nodeWidthAccessor,
        nodePadding: nodePaddingAccessor,
        size: sizeAccessor,
        extent: extentAccessor,
    })

    function computeNodeLinks({
        nodes: nodeList,
        links: linkList,
    }: {
        nodes: SankeyNode<N, L>[]
        links: SankeyLink<N, L>[]
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
            link.source.sourceLinks.push(link)
            link.target.targetLinks.push(link)
        }
    }

    function computeNodeValues({ nodes: nodeList }: { nodes: SankeyNode<N, L>[] }): void {
        for (const node of nodeList) {
            node.value =
                node.fixedValue === undefined
                    ? Math.max(sum(node.sourceLinks, nodeValue), sum(node.targetLinks, nodeValue))
                    : node.fixedValue
        }
    }

    function computeNodeDepths({ nodes: nodeList }: { nodes: SankeyNode<N, L>[] }): void {
        const n = nodeList.length
        let current = new Set(nodeList)
        let next = new Set<SankeyNode<N, L>>()
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

    function computeNodeHeights({ nodes: nodeList }: { nodes: SankeyNode<N, L>[] }): void {
        const n = nodeList.length
        let current = new Set(nodeList)
        let next = new Set<SankeyNode<N, L>>()
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

    function computeNodeLayers({ nodes: nodeList }: { nodes: SankeyNode<N, L>[] }): SankeyNode<N, L>[][] {
        const x = max(nodeList, (d) => d.depth)! + 1
        const kx = x <= 1 ? 0 : (x1 - x0 - dx) / (x - 1)
        const columns = Array.from({ length: x }, () => [] as SankeyNode<N, L>[])
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

    function initializeNodeBreadths(columns: SankeyNode<N, L>[][]): void {
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

    function computeNodeBreadths(graph: { nodes: SankeyNode<N, L>[] }): void {
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

    function relaxLeftToRight(columns: SankeyNode<N, L>[][], alpha: number, beta: number): void {
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
                const deltaY = (y / w - target.y0) * alpha
                target.y0 += deltaY
                target.y1 += deltaY
                reorderNodeLinks(target)
            }
            if (sort === undefined) {
                column.sort(ascendingBreadth)
            }
            resolveCollisions(column, beta)
        }
    }

    function relaxRightToLeft(columns: SankeyNode<N, L>[][], alpha: number, beta: number): void {
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
                const deltaY = (y / w - source.y0) * alpha
                source.y0 += deltaY
                source.y1 += deltaY
                reorderNodeLinks(source)
            }
            if (sort === undefined) {
                column.sort(ascendingBreadth)
            }
            resolveCollisions(column, beta)
        }
    }

    function resolveCollisions(nodeList: SankeyNode<N, L>[], alpha: number): void {
        const i = nodeList.length >> 1
        const subject = nodeList[i]
        resolveCollisionsBottomToTop(nodeList, subject.y0 - py, i - 1, alpha)
        resolveCollisionsTopToBottom(nodeList, subject.y1 + py, i + 1, alpha)
        resolveCollisionsBottomToTop(nodeList, y1, nodeList.length - 1, alpha)
        resolveCollisionsTopToBottom(nodeList, y0, 0, alpha)
    }

    function resolveCollisionsTopToBottom(nodeList: SankeyNode<N, L>[], y: number, i: number, alpha: number): void {
        for (; i < nodeList.length; ++i) {
            const node = nodeList[i]
            const deltaY = (y - node.y0) * alpha
            if (deltaY > 1e-6) {
                node.y0 += deltaY
                node.y1 += deltaY
            }
            y = node.y1 + py
        }
    }

    function resolveCollisionsBottomToTop(nodeList: SankeyNode<N, L>[], y: number, i: number, alpha: number): void {
        for (; i >= 0; --i) {
            const node = nodeList[i]
            const deltaY = (node.y1 - y) * alpha
            if (deltaY > 1e-6) {
                node.y0 -= deltaY
                node.y1 -= deltaY
            }
            y = node.y0 - py
        }
    }

    function reorderNodeLinks({ sourceLinks, targetLinks }: SankeyNode<N, L>): void {
        for (const { source } of targetLinks) {
            source.sourceLinks.sort(ascendingTargetBreadth)
        }
        for (const { target } of sourceLinks) {
            target.targetLinks.sort(ascendingSourceBreadth)
        }
    }

    function reorderLinks(nodeList: SankeyNode<N, L>[]): void {
        for (const { sourceLinks, targetLinks } of nodeList) {
            sourceLinks.sort(ascendingTargetBreadth)
            targetLinks.sort(ascendingSourceBreadth)
        }
    }

    // Returns the target.y0 that would produce an ideal link from source to target.
    function targetTop(source: SankeyNode<N, L>, target: SankeyNode<N, L>): number {
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
    function sourceTop(source: SankeyNode<N, L>, target: SankeyNode<N, L>): number {
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

    return sankeyLayout
}
