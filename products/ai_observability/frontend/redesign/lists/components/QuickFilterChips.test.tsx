import { cleanup, fireEvent, render } from '@testing-library/react'

import { QuickFilterChip, QuickFilterChips } from './QuickFilterChips'

const CHIPS: QuickFilterChip[] = [
    { id: 'errors', label: 'Errors', count: 12, tone: 'danger' },
    { id: 'feedback', label: 'User feedback', count: null },
]

function chipButton(container: HTMLElement, id: string): HTMLElement {
    const button = container.querySelector<HTMLElement>(`[data-attr="traces-list-quick-filter-${id}"]`)
    if (!button) {
        throw new Error(`No chip ${id}`)
    }
    return button
}

describe('QuickFilterChips', () => {
    afterEach(cleanup)

    it.each<[string | null, string, string]>([
        [null, 'false', 'false'],
        ['errors', 'true', 'false'],
        ['feedback', 'false', 'true'],
    ])('with %s active marks only that chip pressed', (active, errorsPressed, feedbackPressed) => {
        const { container } = render(
            <QuickFilterChips chips={CHIPS} active={active} onToggle={() => {}} data-attr="traces-list" />
        )

        expect(chipButton(container, 'errors').getAttribute('aria-pressed')).toBe(errorsPressed)
        expect(chipButton(container, 'feedback').getAttribute('aria-pressed')).toBe(feedbackPressed)
    })

    it('shows the count beside the label and reports the chip a person toggles', () => {
        const toggled: string[] = []
        const { container } = render(
            <QuickFilterChips
                chips={CHIPS}
                active="errors"
                onToggle={(id) => toggled.push(id)}
                data-attr="traces-list"
            />
        )

        fireEvent.click(chipButton(container, 'feedback'))
        fireEvent.click(chipButton(container, 'errors'))

        expect(toggled).toEqual(['feedback', 'errors'])
        expect(chipButton(container, 'errors').textContent).toBe('Errors12')
        expect(chipButton(container, 'feedback').textContent).toBe('User feedback')
    })
})
