import { render } from '@testing-library/react'

import TabScroller from './TabScroller'

describe('TabScroller', () => {
    it('fills the available output pane height and forwards DOM props', () => {
        const { container } = render(
            <TabScroller data-attr="sql-editor-output-pane-results" className="custom-class">
                <div data-testid="grid">Results</div>
            </TabScroller>
        )

        const scroller = container.querySelector('[data-attr="sql-editor-output-pane-results"]')
        const gridWrapper = container.querySelector('[data-testid="grid"]')?.parentElement

        expect(scroller?.getAttribute('data-attr')).toBe('sql-editor-output-pane-results')
        expect(scroller?.classList.contains('relative')).toBe(true)
        expect(scroller?.classList.contains('flex')).toBe(true)
        expect(scroller?.classList.contains('min-h-0')).toBe(true)
        expect(scroller?.classList.contains('min-w-0')).toBe(true)
        expect(scroller?.classList.contains('flex-1')).toBe(true)
        expect(scroller?.classList.contains('w-full')).toBe(true)
        expect(scroller?.classList.contains('overflow-auto')).toBe(true)
        expect(scroller?.classList.contains('custom-class')).toBe(true)
        expect(gridWrapper?.classList.contains('absolute')).toBe(true)
        expect(gridWrapper?.classList.contains('inset-0')).toBe(true)
        expect(gridWrapper?.classList.contains('min-h-0')).toBe(true)
        expect(gridWrapper?.classList.contains('min-w-0')).toBe(true)
    })
})
