import type { Layout } from 'react-grid-layout'

import type { DashboardFilter, MetricsDashboardVariable } from '~/queries/schema/schema-general'
import type { DashboardTile } from '~/types'

import { MAX_REPEATED_COPIES, expandRepeatedGroups } from './dashboardRepeatedGroups'

const insightTile = (id: number, group_key: string | null): DashboardTile =>
    ({ id, group_key, layouts: {}, color: null, insight: { short_id: `i${id}` } }) as DashboardTile

const textTile = (id: number, group_key: string | null): DashboardTile =>
    ({ id, group_key, layouts: {}, color: null, text: { body: 'text' } }) as DashboardTile

const endpoint = (current: MetricsDashboardVariable['current']): MetricsDashboardVariable => ({
    name: 'endpoint',
    source: 'promql',
    query: 'label_values(endpoint)',
    includeAll: true,
    current,
})
const region: MetricsDashboardVariable = { name: 'region', source: 'custom', current: { values: ['eu'] } }
const filters = (variable: MetricsDashboardVariable): DashboardFilter => ({
    date_from: '-6h',
    metricVariables: [variable, region],
})

const OPTIONS = { endpoint: ['list', 'get', 'create'] }

const positions = (layout: Layout | undefined): Record<string, [number, number]> =>
    Object.fromEntries((layout ?? []).map((item) => [item.i, [item.x, item.y]]))

describe('dashboardRepeatedGroups', () => {
    it.each([
        { name: 'All repeats every option', current: { values: [], all: true }, expected: ['list', 'get', 'create'] },
        { name: 'a selection repeats only its values', current: { values: ['get', 'get'] }, expected: ['get'] },
        {
            name: 'the number of copies has a limit',
            current: { values: Array.from({ length: 50 }, (_, index) => `e${index}`) },
            expected: Array.from({ length: MAX_REPEATED_COPIES }, (_, index) => `e${index}`),
        },
    ])('$name', ({ current, expected }) => {
        const result = expandRepeatedGroups({
            tiles: [insightTile(1, 'endpoints')],
            layouts: { sm: [{ i: '1', x: 0, y: 0, w: 12, h: 3 }] },
            groupRepeats: { endpoints: { variable: 'endpoint', direction: 'vertical' } },
            filters: filters(endpoint(current)),
            options: OPTIONS,
        })

        expect(result.copies.map((copy) => copy.value)).toEqual(expected)
        expect(result.tiles).toEqual([])
    })

    it('binds the variable of each copy to its value and keeps the other filters', () => {
        const { copies } = expandRepeatedGroups({
            tiles: [insightTile(1, 'endpoints')],
            layouts: { sm: [{ i: '1', x: 0, y: 0, w: 12, h: 3 }] },
            groupRepeats: { endpoints: { variable: 'endpoint', direction: 'vertical' } },
            filters: filters(endpoint({ values: [], all: true })),
            options: OPTIONS,
        })

        expect(copies[1].filters).toEqual({
            date_from: '-6h',
            metricVariables: [endpoint({ values: ['get'] }), region],
        })
        expect(new Set(copies.map((copy) => copy.key)).size).toBe(copies.length)
    })

    it('stacks vertical copies of a group and moves the tiles below it down', () => {
        const { tiles, copies, layouts } = expandRepeatedGroups({
            tiles: [
                insightTile(1, 'endpoints'),
                insightTile(2, 'endpoints'),
                textTile(3, 'endpoints'),
                insightTile(4, null),
            ],
            layouts: {
                sm: [
                    { i: '1', x: 0, y: 2, w: 6, h: 3 },
                    { i: '2', x: 6, y: 2, w: 6, h: 3 },
                    { i: '3', x: 0, y: 0, w: 12, h: 2 },
                    { i: '4', x: 0, y: 5, w: 12, h: 4 },
                ],
            },
            groupRepeats: { endpoints: { variable: 'endpoint', direction: 'vertical' } },
            filters: filters(endpoint({ values: ['list', 'get'] })),
            options: OPTIONS,
        })

        expect(tiles.map((tile) => tile.id)).toEqual([3, 4])
        const [list1, list2, get1, get2] = [
            copies.find((copy) => copy.tile.id === 1 && copy.value === 'list')!.key,
            copies.find((copy) => copy.tile.id === 2 && copy.value === 'list')!.key,
            copies.find((copy) => copy.tile.id === 1 && copy.value === 'get')!.key,
            copies.find((copy) => copy.tile.id === 2 && copy.value === 'get')!.key,
        ]
        expect(positions(layouts.sm)).toEqual({
            '3': [0, 0],
            [list1]: [0, 2],
            [list2]: [6, 2],
            [get1]: [0, 5],
            [get2]: [6, 5],
            '4': [0, 8],
        })
    })

    it('puts horizontal copies side by side and wraps them when the row is full', () => {
        const { copies, layouts } = expandRepeatedGroups({
            tiles: [insightTile(1, 'endpoints'), insightTile(2, null)],
            layouts: {
                sm: [
                    { i: '1', x: 0, y: 0, w: 5, h: 3 },
                    { i: '2', x: 0, y: 3, w: 12, h: 4 },
                ],
                xs: [
                    { i: '1', x: 0, y: 0, w: 1, h: 3 },
                    { i: '2', x: 0, y: 3, w: 1, h: 4 },
                ],
            },
            groupRepeats: { endpoints: { variable: 'endpoint', direction: 'horizontal' } },
            filters: filters(endpoint({ values: [], all: true })),
            options: OPTIONS,
        })

        const [list, get, create] = copies.map((copy) => copy.key)
        expect(positions(layouts.sm)).toEqual({ [list]: [0, 0], [get]: [5, 0], [create]: [0, 3], '2': [0, 6] })
        expect(positions(layouts.xs)).toEqual({ [list]: [0, 0], [get]: [0, 3], [create]: [0, 6], '2': [0, 9] })
    })

    it.each([
        { name: 'the options have not loaded', options: {}, groupRepeats: undefined },
        {
            name: 'the variable is not on the dashboard',
            options: OPTIONS,
            groupRepeats: { endpoints: { variable: 'pod' } },
        },
    ])('keeps the original tiles when $name', ({ options, groupRepeats }) => {
        const input = {
            tiles: [insightTile(1, 'endpoints')],
            layouts: { sm: [{ i: '1', x: 0, y: 0, w: 12, h: 3 }] },
            groupRepeats: groupRepeats ?? { endpoints: { variable: 'endpoint', direction: 'vertical' as const } },
            filters: filters(endpoint({ values: [], all: true })),
            options,
        }

        const result = expandRepeatedGroups(input)

        expect(result).toEqual({ tiles: input.tiles, copies: [], layouts: input.layouts })
    })
})
