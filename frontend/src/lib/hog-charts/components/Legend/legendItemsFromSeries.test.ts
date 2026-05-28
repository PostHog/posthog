import type { ChartTheme, Series } from '../../core/types'
import { legendItemsFromSeries } from './legendItemsFromSeries'

const THEME: ChartTheme = { colors: ['#aaa', '#bbb', '#ccc'], backgroundColor: '#fff' }

describe('legendItemsFromSeries', () => {
    it('returns one item per non-excluded series in input order', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [] },
            { key: 'b', label: 'B', data: [] },
            { key: 'c', label: 'C', data: [] },
        ]
        const items = legendItemsFromSeries(series, THEME)
        expect(items.map((i) => i.key)).toEqual(['a', 'b', 'c'])
        expect(items.map((i) => i.label)).toEqual(['A', 'B', 'C'])
    })

    it('uses series.color when it is set', () => {
        const series: Series[] = [{ key: 'a', label: 'A', data: [], color: '#123456' }]
        const [item] = legendItemsFromSeries(series, THEME)
        expect(item.color).toBe('#123456')
    })

    it('falls back to theme.colors[i % theme.colors.length] when color is omitted', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [] },
            { key: 'b', label: 'B', data: [] },
            { key: 'c', label: 'C', data: [] },
            { key: 'd', label: 'D', data: [] },
        ]
        const items = legendItemsFromSeries(series, THEME)
        expect(items.map((i) => i.color)).toEqual(['#aaa', '#bbb', '#ccc', '#aaa'])
    })

    it('drops series where visibility.excluded === true', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [] },
            { key: 'b', label: 'B', data: [], visibility: { excluded: true } },
            { key: 'c', label: 'C', data: [] },
        ]
        const items = legendItemsFromSeries(series, THEME)
        expect(items.map((i) => i.key)).toEqual(['a', 'c'])
    })

    it('keeps the pre-filter color index stable when a series is excluded', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [] },
            { key: 'b', label: 'B', data: [], visibility: { excluded: true } },
            { key: 'c', label: 'C', data: [] },
        ]
        const items = legendItemsFromSeries(series, THEME)
        expect(items.find((i) => i.key === 'c')!.color).toBe('#ccc')
    })

    it('returns an empty array when the input is empty', () => {
        expect(legendItemsFromSeries([], THEME)).toEqual([])
    })

    it('falls back to a sentinel color when the theme palette is empty', () => {
        const series: Series[] = [{ key: 'a', label: 'A', data: [] }]
        const items = legendItemsFromSeries(series, { colors: [] })
        expect(items[0].color).toBeTruthy()
    })
})
