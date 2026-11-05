import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { ProductUsageNamesCell } from './ProductUsageNamesCell'

afterEach(() => cleanup())

const person = {
    row: 'a',
    column: '2026-10-05',
    series: 'pa',
    personId: 'person-a',
    label: 'ana@example.com',
    rank: 1,
    engagedSeconds: 50,
    actionCount: 2,
    actions: [{ event: 'report viewed', count: 2 }],
    topPaths: [],
}
describe('ProductUsageNamesCell', () => {
    it.each([
        ['2026-10-04', false],
        ['2026-10-05', true],
        ['2026-10-11', true],
        ['2026-10-12', false],
    ])('marks first use on %s within the displayed week', (date, newInWeek) => {
        const toggle = jest.fn()
        render(
            <ProductUsageNamesCell
                people={[person]}
                total={4}
                firstUse={[{ row: 'a', series: 'pa', personId: 'person-a', label: person.label, date }]}
                columnKey="2026-10-05"
                interval="week"
                expanded={false}
                onToggle={toggle}
            />
        )
        expect(screen.queryByText('New') !== null).toBe(newInWeek)
        fireEvent.click(screen.getByText('+3 more'))
        expect(toggle).toHaveBeenCalledTimes(1)
    })
})
