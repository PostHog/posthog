import type { ChartTheme, Series } from '../../core/types'
import { proportionLegendItems } from './proportion-bar-data'

const THEME: ChartTheme = { colors: ['#22d3ee', '#f14f58', '#a78bfa'], backgroundColor: '#ffffff' }

function part(key: string, data: number[], extra: Partial<Series> = {}): Series {
    return { key, label: key, data, ...extra }
}

describe('proportionLegendItems', () => {
    it.each([
        {
            name: 'shows each share of the total and the raw value',
            series: [part('matched', [244]), part('partial', [25]), part('missed', [731])],
            expected: ['24.4% · 244', '2.5% · 25', '73.1% · 731'],
        },
        {
            name: 'counts negative and non-finite values as nothing',
            series: [part('a', [30, Number.NaN]), part('b', [-10]), part('c', [10])],
            expected: ['75% · 30', '0% · 0', '25% · 10'],
        },
        {
            name: 'shows 0% instead of NaN when the total is zero',
            series: [part('a', [0]), part('b', [0])],
            expected: ['0% · 0', '0% · 0'],
        },
        {
            name: 'leaves excluded series out of the rows and the total',
            series: [part('a', [50]), part('excluded', [50], { visibility: { excluded: true } }), part('b', [50])],
            expected: ['50% · 50', '50% · 50'],
        },
        {
            name: 'keeps a legend-hidden row without a share, and leaves it out of the total',
            series: [part('a', [50]), part('hidden', [100]), part('b', [150])],
            hiddenKeys: ['hidden'],
            expected: ['25% · 50', undefined, '75% · 150'],
        },
    ])('$name', ({ series, hiddenKeys, expected }) => {
        const items = proportionLegendItems(series, THEME, (value) => value.toLocaleString(), hiddenKeys)
        expect(items.map((item) => item.secondaryLabel)).toEqual(expected)
    })

    it('formats the value with the given formatter', () => {
        const items = proportionLegendItems([part('a', [1200])], THEME, (value) => `$${value}`)
        expect(items[0]).toMatchObject({ key: 'a', label: 'a', secondaryLabel: '100% · $1200' })
    })
})
