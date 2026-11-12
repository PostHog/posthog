import type { FlameChange, FlameNode, FlameNodeDatum } from './types'

/** Children under this share of their parent sort to the end, so they sit together and can bundle. */
export const BUNDLE_FRACTION = 0.01
/** Nodes narrower than this draw inside a "+N more" cell with their small siblings. */
export const MIN_NODE_PX = 3

/** Flattened breadth-first, so each row and each node's children are contiguous index ranges sorted
 *  by x. Positions are in unit space (0..1), so zooming changes the window, not the layout. */
export interface FlameTree<Meta = unknown> {
    size: number
    nodes: FlameNode<Meta>[]
    /** `#k` for a repeated sibling name, or 0. Ids aren't stored because paths cost O(depth²) memory. */
    nameSuffix: Int32Array
    /** First node with a given `id` wins. */
    explicitIds: Map<string, number>
    parent: Int32Array
    depth: Int32Array
    x0: Float64Array
    x1: Float64Array
    value: Float64Array
    self: Float64Array
    childStart: Int32Array
    childCount: Int32Array
    subtreeSize: Int32Array
    subtreeMaxDepth: Int32Array
    /** `rowStart[maxDepth + 1]` is `size`. */
    rowStart: Int32Array
    /** -1 for an empty tree. */
    maxDepth: number
    totalValue: number
    hasBaseline: boolean
    hasGroups: boolean
}

export type FlameFocus = { kind: 'node'; index: number } | { kind: 'bundle'; first: number; last: number } | null

export interface FlameWindow {
    x0: number
    x1: number
}

export interface FlameCell {
    kind: 'node' | 'bundle'
    /** First node of a bundle. */
    index: number
    /** Equal to `index` for a node. */
    last: number
    depth: number
    /** Px relative to the plot, not clamped to it. */
    x0: number
    x1: number
}

const positive = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0)

const weightOf = (node: FlameNode<unknown>): number => Math.max(positive(node.value), positive(node.baselineValue))

function orderChildren<Meta>(children: FlameNode<Meta>[], parentWeight: number): FlameNode<Meta>[] {
    const cutoff = parentWeight * BUNDLE_FRACTION
    let small = 0
    for (const child of children) {
        if (weightOf(child) < cutoff) {
            small++
        }
    }
    if (small < 2) {
        return children
    }
    const large: FlameNode<Meta>[] = []
    const tail: FlameNode<Meta>[] = []
    for (const child of children) {
        ;(weightOf(child) < cutoff ? tail : large).push(child)
    }
    tail.sort((a, b) => weightOf(b) - weightOf(a))
    return large.concat(tail)
}

export function buildFlameTree<Meta>(data: FlameNode<Meta> | FlameNode<Meta>[]): FlameTree<Meta> {
    // Skipping a node object reached twice also stops cyclic input from looping forever.
    const seen = new Set<FlameNode<Meta>>()
    const roots = (Array.isArray(data) ? data : [data]).filter((root) => {
        if (!root || seen.has(root)) {
            return false
        }
        seen.add(root)
        return true
    })

    const nodes: FlameNode<Meta>[] = []
    const parent: number[] = []
    const depth: number[] = []
    const x0: number[] = []
    const x1: number[] = []
    const nameSuffix: number[] = []
    const explicitIds = new Map<string, number>()
    const childStart: number[] = []
    const childCount: number[] = []
    let hasBaseline = false
    let hasGroups = false

    const suffixes = new Map<FlameNode<Meta>, number>()
    const claimedIds = new Set<string>()
    const ownsId = new Set<FlameNode<Meta>>()
    /** Suffixes follow input order, so sorting siblings never changes a node's default id. */
    const assignSuffixes = (siblings: FlameNode<Meta>[]): void => {
        const seenNames = new Map<string, number>()
        for (const sibling of siblings) {
            if (sibling.id !== undefined && !claimedIds.has(sibling.id)) {
                claimedIds.add(sibling.id)
                ownsId.add(sibling)
                continue
            }
            const name = String(sibling.name ?? '')
            const count = (seenNames.get(name) ?? 0) + 1
            seenNames.set(name, count)
            if (count > 1) {
                suffixes.set(sibling, count)
            }
        }
    }

    const push = (node: FlameNode<Meta>, parentIndex: number, left: number, right: number): void => {
        const index = nodes.length
        nodes.push(node)
        parent.push(parentIndex)
        depth.push(parentIndex < 0 ? 0 : depth[parentIndex] + 1)
        x0.push(left)
        x1.push(right)
        nameSuffix.push(suffixes.get(node) ?? 0)
        if (node.id !== undefined && ownsId.has(node)) {
            explicitIds.set(node.id, index)
        }
        hasBaseline ||= node.baselineValue !== undefined
        hasGroups ||= !!node.group
    }

    assignSuffixes(roots)
    const rootWeight = roots.reduce((sum, root) => sum + weightOf(root), 0)
    let cursor = 0
    for (const root of roots) {
        const width = rootWeight > 0 ? weightOf(root) / rootWeight : 0
        push(root, -1, cursor, cursor + width)
        cursor += width
    }

    for (let head = 0; head < nodes.length; head++) {
        childStart[head] = nodes.length
        const children = nodes[head].children
        if (children && children.length > 0) {
            const fresh = children.filter((child) => {
                if (!child || seen.has(child)) {
                    return false
                }
                seen.add(child)
                return true
            })
            assignSuffixes(fresh)
            const parentWeight = weightOf(nodes[head])
            const ordered = orderChildren(fresh, parentWeight)
            const childWeight = ordered.reduce((sum, child) => sum + weightOf(child), 0)
            const span = x1[head] - x0[head]
            const unit = parentWeight > 0 ? span / Math.max(parentWeight, childWeight) : 0
            let left = x0[head]
            for (const child of ordered) {
                const right = Math.min(x1[head], left + weightOf(child) * unit)
                push(child, head, left, right)
                left = right
            }
        }
        childCount[head] = nodes.length - childStart[head]
    }

    const size = nodes.length
    const value = new Float64Array(size)
    const self = new Float64Array(size)
    const subtreeSize = new Int32Array(size)
    const subtreeMaxDepth = new Int32Array(size)
    for (let i = 0; i < size; i++) {
        value[i] = positive(nodes[i].value)
    }
    for (let i = size - 1; i >= 0; i--) {
        let childValue = 0
        for (let c = childStart[i], end = c + childCount[i]; c < end; c++) {
            childValue += value[c]
        }
        self[i] = Math.max(0, value[i] - childValue)
        subtreeSize[i] += 1
        subtreeMaxDepth[i] = Math.max(subtreeMaxDepth[i], depth[i])
        const p = parent[i]
        if (p >= 0) {
            subtreeSize[p] += subtreeSize[i]
            subtreeMaxDepth[p] = Math.max(subtreeMaxDepth[p], subtreeMaxDepth[i])
        }
    }

    const maxDepth = size > 0 ? depth[size - 1] : -1
    const rowStart = new Int32Array(maxDepth + 2)
    for (let d = 0, i = 0; d <= maxDepth + 1; d++) {
        while (i < size && depth[i] < d) {
            i++
        }
        rowStart[d] = i
    }

    let totalValue = 0
    for (let i = 0; i < size && depth[i] === 0; i++) {
        totalValue += value[i]
    }

    return {
        size,
        nodes,
        nameSuffix: Int32Array.from(nameSuffix),
        explicitIds,
        parent: Int32Array.from(parent),
        depth: Int32Array.from(depth),
        x0: Float64Array.from(x0),
        x1: Float64Array.from(x1),
        value,
        self,
        childStart: Int32Array.from(childStart),
        childCount: Int32Array.from(childCount),
        subtreeSize,
        subtreeMaxDepth,
        rowStart,
        maxDepth,
        totalValue,
        hasBaseline,
        hasGroups,
    }
}

function idSegment(tree: FlameTree<unknown>, index: number): string {
    const name = String(tree.nodes[index].name ?? '').replace(/[\\/#]/g, '\\$&')
    const suffix = tree.nameSuffix[index]
    return suffix > 0 ? `${name}#${suffix}` : name
}

function ownId(tree: FlameTree<unknown>, index: number): string | undefined {
    const id = tree.nodes[index].id
    return id !== undefined && tree.explicitIds.get(id) === index ? id : undefined
}

/** Own `id`, else the `/`-joined path of names from the root or the nearest ancestor with an `id`. */
export function nodeId(tree: FlameTree<unknown>, index: number): string {
    const parts: string[] = []
    for (let i = index; i >= 0; i = tree.parent[i]) {
        const own = ownId(tree, i)
        if (own !== undefined) {
            parts.push(own)
            break
        }
        parts.push(idSegment(tree, i))
    }
    return parts.reverse().join('/')
}

/** Walks only branches whose path prefixes `id`, comparing in place, so a lookup builds no path strings. */
export function indexOfId(tree: FlameTree<unknown>, id: string): number | undefined {
    const explicit = tree.explicitIds.get(id)
    if (explicit !== undefined) {
        return explicit
    }
    // Each entry is a node whose id matches `id` up to `end`.
    const stack: { index: number; end: number }[] = []
    const tryEnter = (index: number, start: number): void => {
        const segment = idSegment(tree, index)
        const end = start + segment.length
        if (id.startsWith(segment, start) && (end === id.length || id[end] === '/')) {
            stack.push({ index, end })
        }
    }
    for (let i = 0; i < tree.size && tree.depth[i] === 0; i++) {
        if (ownId(tree, i) === undefined) {
            tryEnter(i, 0)
        }
    }
    for (const [own, index] of tree.explicitIds) {
        if (id.length > own.length && id[own.length] === '/' && id.startsWith(own)) {
            stack.push({ index, end: own.length })
        }
    }
    while (stack.length > 0) {
        const { index, end } = stack.pop()!
        if (end === id.length) {
            return index
        }
        for (let c = tree.childStart[index], last = c + tree.childCount[index]; c < last; c++) {
            if (ownId(tree, c) === undefined) {
                tryEnter(c, end + 1)
            }
        }
    }
    return undefined
}

/** A focus with no width falls back to the whole graph. */
export function focusWindow(tree: FlameTree<unknown>, focus: FlameFocus): FlameWindow {
    if (focus?.kind === 'node' && tree.x1[focus.index] > tree.x0[focus.index]) {
        return { x0: tree.x0[focus.index], x1: tree.x1[focus.index] }
    }
    if (focus?.kind === 'bundle' && tree.x1[focus.last] > tree.x0[focus.first]) {
        return { x0: tree.x0[focus.first], x1: tree.x1[focus.last] }
    }
    return { x0: 0, x1: 1 }
}

/** Ancestors above the focus plus its deepest descendant. */
export function focusRowCount(tree: FlameTree<unknown>, focus: FlameFocus): number {
    if (focus?.kind === 'node') {
        return tree.subtreeMaxDepth[focus.index] + 1
    }
    if (focus?.kind === 'bundle') {
        let deepest = tree.depth[focus.first]
        for (let i = focus.first; i <= focus.last; i++) {
            deepest = Math.max(deepest, tree.subtreeMaxDepth[i])
        }
        return deepest + 1
    }
    return tree.maxDepth + 1
}

function pushRun(cells: FlameCell[], run: FlameCell): void {
    cells.push(run.index === run.last ? { ...run, kind: 'node' } : run)
}

/** Binary search, valid because right edges never decrease along a row. */
function firstEndingAfter(x1: Float64Array, lo: number, hi: number, x: number): number {
    while (lo < hi) {
        const mid = (lo + hi) >>> 1
        if (x1[mid] <= x) {
            lo = mid + 1
        } else {
            hi = mid
        }
    }
    return lo
}

/** Runs of siblings under {@link MIN_NODE_PX} merge into one bundle cell, and children of a narrow
 *  node are skipped. Cells come out sorted by depth, then x. */
export function computeFlameCells(
    tree: FlameTree<unknown>,
    window: FlameWindow,
    width: number,
    depthStart: number,
    depthEnd: number
): FlameCell[] {
    const cells: FlameCell[] = []
    const span = window.x1 - window.x0
    if (span <= 0 || width <= 0 || tree.size === 0) {
        return cells
    }
    const scale = width / span
    const { x0, x1, parent, rowStart } = tree
    const lastDepth = Math.min(depthEnd, tree.maxDepth)

    for (let d = Math.max(0, depthStart); d <= lastDepth; d++) {
        const rowEnd = rowStart[d + 1]
        let run: FlameCell | null = null
        let runParent = -1
        for (let i = firstEndingAfter(x1, rowStart[d], rowEnd, window.x0); i < rowEnd && x0[i] < window.x1; i++) {
            const w = (x1[i] - x0[i]) * scale
            if (w <= 0) {
                continue
            }
            const p = parent[i]
            if (p >= 0 && (x1[p] - x0[p]) * scale < MIN_NODE_PX) {
                // Siblings are contiguous, so skip the rest of this narrow parent's children at once.
                i = tree.childStart[p] + tree.childCount[p] - 1
                continue
            }
            const left = (x0[i] - window.x0) * scale
            const right = (x1[i] - window.x0) * scale
            if (w >= MIN_NODE_PX) {
                if (run) {
                    pushRun(cells, run)
                    run = null
                }
                cells.push({ kind: 'node', index: i, last: i, depth: d, x0: left, x1: right })
            } else if (run && runParent === p) {
                run.last = i
                run.x1 = right
            } else {
                if (run) {
                    pushRun(cells, run)
                }
                run = { kind: 'bundle', index: i, last: i, depth: d, x0: left, x1: right }
                runParent = p
            }
        }
        if (run) {
            pushRun(cells, run)
        }
    }
    return cells
}

/** Lets the pointer reach slivers and narrow "+N more" cells. */
export const HIT_SLOP_PX = 4

/** `cells` must be sorted by depth, then x. */
export function cellAt(cells: readonly FlameCell[], depth: number, x: number): FlameCell | null {
    let lo = 0
    let hi = cells.length
    while (lo < hi) {
        const mid = (lo + hi) >>> 1
        if (cells[mid].depth < depth) {
            lo = mid + 1
        } else {
            hi = mid
        }
    }
    hi = cells.length
    while (lo < hi) {
        const mid = (lo + hi) >>> 1
        if (cells[mid].depth === depth && cells[mid].x1 <= x - HIT_SLOP_PX) {
            lo = mid + 1
        } else {
            hi = mid
        }
    }
    let nearest: FlameCell | null = null
    let nearestDistance = HIT_SLOP_PX
    for (let i = lo; i < cells.length && cells[i].depth === depth && cells[i].x0 <= x + HIT_SLOP_PX; i++) {
        const cell = cells[i]
        if (x >= cell.x0 && x < cell.x1) {
            return cell
        }
        const distance = x < cell.x0 ? cell.x0 - x : x - cell.x1
        if (distance <= nearestDistance) {
            nearest = cell
            nearestDistance = distance
        }
    }
    return nearest
}

export function ancestorPath(tree: FlameTree<unknown>, index: number): number[] {
    const path: number[] = []
    for (let i = index; i >= 0; i = tree.parent[i]) {
        path.push(i)
    }
    return path.reverse()
}

export interface FlameDiffOptions {
    comparing: boolean
    threshold: number
    minCount: number
}

export function classifyChange(node: FlameNode<unknown>, options: FlameDiffOptions): FlameChange {
    if (node.baselineValue === undefined && !options.comparing) {
        return { kind: 'none', ratio: null }
    }
    const value = positive(node.value)
    const baseline = positive(node.baselineValue)
    if (baseline === 0) {
        return { kind: value > 0 ? 'new' : 'none', ratio: null }
    }
    if (value === 0) {
        return { kind: 'gone', ratio: 0 }
    }
    const ratio = value / baseline
    const { count, baselineCount } = node
    if (
        options.minCount > 0 &&
        count !== undefined &&
        baselineCount !== undefined &&
        Math.min(count, baselineCount) < options.minCount
    ) {
        return { kind: 'low-sample', ratio }
    }
    if (ratio > 1 + options.threshold) {
        return { kind: 'slower', ratio }
    }
    if (ratio < 1 - options.threshold) {
        return { kind: 'faster', ratio }
    }
    return { kind: 'similar', ratio }
}

export interface FlameSearchResult {
    matches: Uint8Array
    /** Lets a bundle tell whether it hides a match. */
    containsMatch: Uint8Array
    count: number
    /** 0..1 of the width; a match nested in another match counts once. */
    fraction: number
}

const lowerNamesCache = new WeakMap<FlameTree<unknown>, string[]>()

export function searchFlame(tree: FlameTree<unknown>, query: string | undefined): FlameSearchResult | null {
    const needle = query?.trim().toLowerCase()
    if (!needle) {
        return null
    }
    let names = lowerNamesCache.get(tree)
    if (!names) {
        names = tree.nodes.map((node) => String(node.name ?? '').toLowerCase())
        lowerNamesCache.set(tree, names)
    }
    const { size, parent } = tree
    const matches = new Uint8Array(size)
    const containsMatch = new Uint8Array(size)
    const insideMatch = new Uint8Array(size)
    let count = 0
    let covered = 0
    for (let i = 0; i < size; i++) {
        const p = parent[i]
        insideMatch[i] = p >= 0 && (matches[p] || insideMatch[p]) ? 1 : 0
        if (names[i].includes(needle)) {
            matches[i] = 1
            count++
            // Laid-out widths, because concurrent children are scaled down to fit their parent.
            if (!insideMatch[i]) {
                covered += tree.x1[i] - tree.x0[i]
            }
        }
    }
    for (let i = size - 1; i >= 0; i--) {
        containsMatch[i] |= matches[i]
        const p = parent[i]
        if (p >= 0 && containsMatch[i]) {
            containsMatch[p] = 1
        }
    }
    return { matches, containsMatch, count, fraction: Math.min(1, covered) }
}

const share = (part: number, whole: number): number => (whole > 0 ? part / whole : 0)

export function nodeDatum<Meta>(tree: FlameTree<Meta>, index: number, diff: FlameDiffOptions): FlameNodeDatum<Meta> {
    const node = tree.nodes[index]
    const p = tree.parent[index]
    const value = tree.value[index]
    return {
        id: nodeId(tree, index),
        name: node.name,
        value,
        self: tree.self[index],
        baselineValue: node.baselineValue,
        count: node.count,
        baselineCount: node.baselineCount,
        group: node.group,
        meta: node.meta,
        depth: tree.depth[index],
        parentId: p >= 0 ? nodeId(tree, p) : null,
        fractionOfParent: share(value, p >= 0 ? tree.value[p] : tree.totalValue),
        fractionOfRoot: share(value, tree.totalValue),
        change: classifyChange(node, diff),
        node,
    }
}

export interface FlameRowGeometry {
    rowHeight: number
    rowCount: number
}

export function rowTop(depth: number, { rowHeight }: FlameRowGeometry): number {
    return depth * rowHeight
}

/** -1 outside the rows. */
export function depthAtY(y: number, { rowHeight, rowCount }: FlameRowGeometry): number {
    const row = Math.floor(y / rowHeight)
    return row < 0 || row >= rowCount ? -1 : row
}

export function visibleDepths(
    scrollTop: number,
    height: number,
    { rowHeight, rowCount }: FlameRowGeometry
): [number, number] {
    return [
        Math.max(0, Math.floor(scrollTop / rowHeight)),
        Math.min(rowCount - 1, Math.ceil((scrollTop + height) / rowHeight) - 1),
    ]
}
