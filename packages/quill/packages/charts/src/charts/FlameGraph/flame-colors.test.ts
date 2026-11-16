import type { ChartTheme } from '../../core/types'
import { computeFlameColors, resolveInk } from './flame-colors'
import { buildFlameTree } from './flame-layout'
import type { FlameNode } from './types'

const THEME: ChartTheme = {
    colors: ['#1d4aff', '#621da6', '#42827e', '#ce0e74', '#f14f58'],
    backgroundColor: '#ffffff',
}
const INK = resolveInk(THEME)
const DIFF = { comparing: false, threshold: 0.1, minCount: 0 }

const TREE: FlameNode = {
    name: 'root',
    value: 100,
    group: 'api',
    children: [
        { name: 'query', value: 40, group: 'db' },
        { name: 'failed', value: 20, group: 'api', color: '#ff0000' },
        { name: 'inherited', value: 10, group: 'toString' },
    ],
}

describe('computeFlameColors', () => {
    it('fills a group from groupColors without spending a palette slot, and a node color fills that node alone', () => {
        const tree = buildFlameTree(TREE)
        const fillOf = (colors: ReturnType<typeof computeFlameColors>, name: string): string =>
            colors.fills[tree.nodes.findIndex((node) => node.name === name)]
        const legendColor = (colors: ReturnType<typeof computeFlameColors>, key: string): string | undefined =>
            colors.legend.find((item) => item.key === key)?.color

        const palette = computeFlameColors(tree, 'group', THEME, INK, DIFF)
        const custom = computeFlameColors(tree, 'group', THEME, INK, DIFF, { api: '#00aa00' })

        expect(fillOf(custom, 'root')).not.toBe(fillOf(palette, 'root'))
        expect(legendColor(custom, 'api')).toBe(fillOf(custom, 'root'))
        expect(fillOf(custom, 'query')).toBe(fillOf(palette, 'root'))
        expect(fillOf(custom, 'failed')).not.toBe(fillOf(custom, 'root'))
        expect(fillOf(custom, 'failed')).toBe(fillOf(palette, 'failed'))
        // A group named like an Object.prototype member still takes a palette slot.
        expect(fillOf(custom, 'inherited')).toBe(fillOf(palette, 'query'))
    })
})
