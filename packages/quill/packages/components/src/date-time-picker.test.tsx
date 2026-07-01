import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { CUSTOM_RANGE } from './date-time-ranges'
import { DateTimePicker } from './date-time-picker'

// The day grid wraps each Button in a div carrying the data-is-* range flags.
const dayCell = (label: string): HTMLElement => {
    const cell = screen.getByLabelText(label).closest('[data-is-start]')
    if (!(cell instanceof HTMLElement)) {
        throw new Error(`No range-flagged day cell found for "${label}"`)
    }
    return cell
}

// Range entirely inside value.end's month (January), which the always-rendered right calendar shows.
const VALUE = { start: new Date(2023, 0, 10), end: new Date(2023, 0, 20), range: CUSTOM_RANGE }
const MAX = new Date(2030, 0, 1)

describe('DateTimePicker', () => {
    afterEach(cleanup)

    it('marks the range start, end, and in-between days from the shared grid', () => {
        render(<DateTimePicker value={VALUE} maxDate={MAX} onApply={jest.fn()} onCancel={jest.fn()} />)

        expect(dayCell('Select Jan 10, 2023').getAttribute('data-is-start')).toBe('true')
        expect(dayCell('Select Jan 20, 2023').getAttribute('data-is-end')).toBe('true')
        expect(dayCell('Select Jan 15, 2023').getAttribute('data-is-between')).toBe('true')

        const outside = dayCell('Select Jan 25, 2023')
        expect(outside.getAttribute('data-is-start')).toBe('false')
        expect(outside.getAttribute('data-is-end')).toBe('false')
        expect(outside.getAttribute('data-is-between')).toBe('false')
    })

    it('applies the current range unchanged', async () => {
        const onApply = jest.fn()
        render(<DateTimePicker value={VALUE} maxDate={MAX} onApply={onApply} onCancel={jest.fn()} />)

        await userEvent.click(screen.getByLabelText('Apply date range'))

        expect(onApply).toHaveBeenCalledTimes(1)
        const applied = onApply.mock.calls[0][0]
        expect([applied.start.getDate(), applied.end.getDate()]).toEqual([10, 20])
        expect(applied.range).toBe(CUSTOM_RANGE)
    })
})
