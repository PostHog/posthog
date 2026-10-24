import {
    buildFlameTree,
    cellAt,
    classifyChange,
    computeFlameCells,
    depthAtY,
    focusRowCount,
    focusWindow,
    rowTop,
    searchFlame,
    visibleDepths,
} from './flame-layout'
import type { FlameChangeKind, FlameNode } from './types'

const TREE: FlameNode = {
    name: 'root',
    value: 100,
    children: [
        { name: 'a', value: 60, children: [{ name: 'a1', value: 30 }] },
        { name: 'b', value: 30 },
    ],
}

function spanOf(tree: ReturnType<typeof buildFlameTree>, id: string): [number, number] {
    const index = tree.idToIndex.get(id)!
    const round = (v: number): number => Math.round(v * 1e6) / 1e6
    return [round(tree.x0[index]), round(tree.x1[index])]
}

describe('flame layout', () => {
    it('lays children out inside their parent and derives self value', () => {
        const tree = buildFlameTree(TREE)
        expect(spanOf(tree, 'root')).toEqual([0, 1])
        expect(spanOf(tree, 'root/a')).toEqual([0, 0.6])
        expect(spanOf(tree, 'root/b')).toEqual([0.6, 0.9])
        expect(spanOf(tree, 'root/a/a1')).toEqual([0, 0.3])
        expect(Array.from(tree.self)).toEqual([10, 30, 30, 30])
        expect(tree.maxDepth).toBe(2)
        expect(Array.from(tree.rowStart)).toEqual([0, 1, 3, 4])
    })

    it('scales concurrent children that add up to more than their parent down to fit it', () => {
        const tree = buildFlameTree({
            name: 'p',
            value: 10,
            children: [
                { name: 'x', value: 10 },
                { name: 'y', value: 10 },
            ],
        })
        expect(spanOf(tree, 'p/x')).toEqual([0, 0.5])
        expect(spanOf(tree, 'p/y')).toEqual([0.5, 1])
        expect(tree.self[0]).toBe(0)
    })

    it('sizes by the larger of value and baseline, so a gone node keeps its room', () => {
        const tree = buildFlameTree({
            name: 'p',
            value: 50,
            baselineValue: 100,
            children: [
                { name: 'kept', value: 40, baselineValue: 40 },
                { name: 'gone', value: 0, baselineValue: 60 },
            ],
        })
        expect(spanOf(tree, 'p/kept')).toEqual([0, 0.4])
        expect(spanOf(tree, 'p/gone')).toEqual([0.4, 1])
    })

    it('moves two or more children under 1% of the parent to the end, largest first', () => {
        const tree = buildFlameTree({
            name: 'p',
            value: 1000,
            children: [
                { name: 'tiny1', value: 1 },
                { name: 'big', value: 500 },
                { name: 'tiny2', value: 5 },
                { name: 'medium', value: 300 },
            ],
        })
        const order = Array.from({ length: tree.childCount[0] }, (_, i) => tree.nodes[tree.childStart[0] + i].name)
        expect(order).toEqual(['big', 'medium', 'tiny2', 'tiny1'])
    })

    it('gives repeated sibling names distinct ids and skips a node object reached twice', () => {
        const shared: FlameNode = { name: 'dup', value: 1 }
        const cyclic: FlameNode = { name: 'loop', value: 4, children: [shared, { name: 'dup', value: 1 }] }
        cyclic.children!.push(cyclic, shared)
        const tree = buildFlameTree(cyclic)
        expect(tree.ids).toEqual(['loop', 'loop/dup', 'loop/dup#2'])
    })

    it.each([
        { data: [], label: 'no roots' },
        { data: { name: 'zero', value: 0 }, label: 'a zero-value root' },
    ])('builds an empty-width tree from $label without throwing', ({ data }) => {
        const tree = buildFlameTree(data as FlameNode | FlameNode[])
        expect(computeFlameCells(tree, { x0: 0, x1: 1 }, 800, 0, 10)).toEqual([])
    })

    it('zooms to the focused node, keeps its ancestors full width and drops its siblings', () => {
        const tree = buildFlameTree(TREE)
        const focus = { kind: 'node' as const, index: tree.idToIndex.get('root/a')! }
        const window = focusWindow(tree, focus)
        expect(window).toEqual({ x0: 0, x1: 0.6 })
        expect(focusRowCount(tree, focus)).toBe(3)

        const cells = computeFlameCells(tree, window, 600, 0, 2)
        const drawn = cells.map((cell) => [tree.ids[cell.index], Math.round(cell.x0), Math.round(cell.x1)])
        expect(drawn).toEqual([
            ['root', 0, 1000],
            ['root/a', 0, 600],
            ['root/a/a1', 0, 300],
        ])
        expect(tree.ids[cellAt(cells, 2, 299)!.index]).toBe('root/a/a1')
        expect(tree.ids[cellAt(cells, 2, 303)!.index]).toBe('root/a/a1')
        expect(cellAt(cells, 2, 305)).toBeNull()
    })

    it('bundles a run of narrow siblings, keeps a lone narrow node, and skips children of narrow nodes', () => {
        const tree = buildFlameTree({
            name: 'p',
            value: 1000,
            children: [
                { name: 'big', value: 900, children: [{ name: 'lone', value: 1 }] },
                { name: 's1', value: 2, children: [{ name: 'hidden', value: 1 }] },
                { name: 's2', value: 2 },
                { name: 's3', value: 2 },
            ],
        })
        const cells = computeFlameCells(tree, { x0: 0, x1: 1 }, 1000, 0, 2)
        const summary = cells.map((cell) => `${cell.kind}:${tree.nodes[cell.index].name}-${tree.nodes[cell.last].name}`)
        expect(summary).toEqual(['node:p-p', 'node:big-big', 'bundle:s1-s3', 'node:lone-lone'])
    })

    it.each<[string, Partial<FlameNode>, FlameChangeKind]>([
        ['grew past the threshold', { value: 130, baselineValue: 100 }, 'slower'],
        ['shrank past the threshold', { value: 70, baselineValue: 100 }, 'faster'],
        ['moved within the threshold', { value: 115, baselineValue: 100 }, 'similar'],
        ['has no baseline', { value: 10 }, 'new'],
        ['has no current value', { value: 0, baselineValue: 10 }, 'gone'],
        ['has too few samples', { value: 300, baselineValue: 100, count: 500, baselineCount: 4 }, 'low-sample'],
        ['has no counts to gate on', { value: 300, baselineValue: 100 }, 'slower'],
    ])('classifies a node that %s', (_, node, kind) => {
        const change = classifyChange(
            { name: 'n', value: 0, ...node },
            { comparing: true, threshold: 0.2, minCount: 10 }
        )
        expect(change.kind).toBe(kind)
    })

    it('counts a match inside another match once toward the matched share', () => {
        const tree = buildFlameTree({
            name: 'root',
            value: 100,
            children: [
                { name: 'db.query', value: 40, children: [{ name: 'db.connect', value: 10 }] },
                { name: 'render', value: 20, children: [{ name: 'db.cache', value: 5 }] },
            ],
        })
        const result = searchFlame(tree, ' DB. ')!
        expect(result.count).toBe(3)
        expect(result.fraction).toBeCloseTo(0.45)
        expect(result.containsMatch[tree.idToIndex.get('root/render')!]).toBe(1)
        expect(searchFlame(tree, '   ')).toBeNull()
    })

    it.each([
        { direction: 'top-down' as const, topDepth: 0, rows: [0, 2] },
        { direction: 'bottom-up' as const, topDepth: 9, rows: [7, 9] },
    ])('maps rows to depths $direction', ({ direction, topDepth, rows }) => {
        const geometry = { rowHeight: 20, rowCount: 10, direction }
        expect(depthAtY(5, geometry)).toBe(topDepth)
        expect(rowTop(topDepth, geometry)).toBe(0)
        expect(depthAtY(-1, geometry)).toBe(-1)
        expect(depthAtY(200, geometry)).toBe(-1)
        expect(visibleDepths(0, 50, geometry)).toEqual(rows)
    })
})
