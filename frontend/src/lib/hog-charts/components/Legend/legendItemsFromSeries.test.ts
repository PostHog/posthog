import type { ChartTheme, Series } from '../../core/types'
import { legendItemsFromSeries } from './legendItemsFromSeries'

const THEME: ChartTheme = { colors: ['#aaa', '#bbb', '#ccc'], backgroundColor: '#fff' }

describe('legendItemsFromSeries', () => {
    it('uses series.color when set and falls back to theme.colors[i % len] otherwise', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [], color: '#123' },
            { key: 'b', label: 'B', data: [] },
            { key: 'c', label: 'C', data: [] },
            { key: 'd', label: 'D', data: [] },
        ]
        expect(legendItemsFromSeries(series, THEME).map((i) => i.color)).toEqual(['#123', '#bbb', '#ccc', '#aaa'])
    })

    it('drops excluded series and keeps the pre-filter color index of the rest', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [] },
            { key: 'b', label: 'B', data: [], visibility: { excluded: true } },
            { key: 'c', label: 'C', data: [] },
        ]
        const items = legendItemsFromSeries(series, THEME)
        expect(items.map((i) => i.key)).toEqual(['a', 'c'])
        expect(items[1].color).toBe('#ccc')
    })

    it('drops overlay series by default (trendlines, moving averages)', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [] },
            { key: 'a-trend', label: 'A (trend)', data: [], overlay: true },
            { key: 'b', label: 'B', data: [] },
            { key: 'b-ma', label: 'B (moving avg)', data: [], overlay: true },
        ]
        const items = legendItemsFromSeries(series, THEME)
        expect(items.map((i) => i.key)).toEqual(['a', 'b'])
        expect(items.map((i) => i.color)).toEqual(['#aaa', '#ccc'])
    })

    it('keeps overlay series when includeOverlay is true', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [] },
            { key: 'a-trend', label: 'A (trend)', data: [], overlay: true },
        ]
        const items = legendItemsFromSeries(series, THEME, { includeOverlay: true })
        expect(items.map((i) => i.key)).toEqual(['a', 'a-trend'])
    })
})
