import { formatWidgetListCountFooter, WIDGET_LIST_COUNT_RECORDINGS } from '../components/WidgetCard/WidgetCardBody'

describe('formatWidgetListCountFooter', () => {
    it('formats exact totals for issues', () => {
        expect(formatWidgetListCountFooter(1, 1, false)).toBe('1 of 1 issue')
        expect(formatWidgetListCountFooter(3, 12, false)).toBe('3 of 12 issues')
    })

    it('formats capped totals for issues', () => {
        expect(formatWidgetListCountFooter(1, 25, true)).toBe('1 of 25+ issues')
    })

    it('falls back when total is missing', () => {
        expect(formatWidgetListCountFooter(2, undefined)).toBe('2 issues')
    })

    it('shows lower-bound style footer when hasMore and total is omitted', () => {
        expect(formatWidgetListCountFooter(10, undefined, undefined, undefined, true)).toBe('10+ issues')
        expect(formatWidgetListCountFooter(1, undefined, undefined, undefined, true)).toBe('1+ issue')
    })

    it('formats exact totals for recordings', () => {
        expect(formatWidgetListCountFooter(1, 1, false, WIDGET_LIST_COUNT_RECORDINGS)).toBe('1 of 1 recording')
        expect(formatWidgetListCountFooter(3, 12, false, WIDGET_LIST_COUNT_RECORDINGS)).toBe('3 of 12 recordings')
    })

    it('formats capped totals for recordings', () => {
        expect(formatWidgetListCountFooter(2, 25, true, WIDGET_LIST_COUNT_RECORDINGS)).toBe('2 of 25+ recordings')
    })

    it('falls back for recordings when total is missing', () => {
        expect(formatWidgetListCountFooter(2, undefined, undefined, WIDGET_LIST_COUNT_RECORDINGS)).toBe('2 recordings')
    })
})
