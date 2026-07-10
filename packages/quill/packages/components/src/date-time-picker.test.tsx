import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { CUSTOM_RANGE, type DateTimeRange } from './date-time-ranges'
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

    it('renders the provided ranges instead of the default quick ranges', () => {
        const ranges: DateTimeRange[] = [
            { id: 1, name: 'This month', rangeSetter: (d) => d },
            { id: 2, name: 'Year to date', rangeSetter: (d) => d },
        ]
        render(<DateTimePicker value={VALUE} maxDate={MAX} onApply={jest.fn()} ranges={ranges} />)

        expect(screen.getByTitle('This month')).toBeTruthy()
        expect(screen.getByTitle('Year to date')).toBeTruthy()
        expect(screen.queryByTitle('Last 7 days')).toBeNull()
    })

    it('applies a quick range immediately when applyOnRangeSelect is set', async () => {
        const onApply = jest.fn()
        const lastMonth: DateTimeRange = {
            id: 1,
            name: 'Last month',
            rangeSetter: () => new Date(2022, 11, 1),
            endSetter: () => new Date(2022, 11, 31, 23, 59, 59),
        }
        render(<DateTimePicker value={VALUE} maxDate={MAX} onApply={onApply} ranges={[lastMonth]} applyOnRangeSelect />)

        await userEvent.click(screen.getByTitle('Last month'))

        expect(onApply).toHaveBeenCalledTimes(1)
        const applied = onApply.mock.calls[0][0]
        expect(applied.start).toEqual(new Date(2022, 11, 1))
        expect(applied.range).toBe(lastMonth)
    })

    it('renders the rangesFooter in the rail, even with no presets', () => {
        const { unmount } = render(
            <DateTimePicker value={VALUE} maxDate={MAX} onApply={jest.fn()} rangesFooter={<span>Rolling input</span>} />
        )
        expect(screen.getByText('Rolling input')).toBeTruthy()
        unmount()

        // ranges={[]} hides the presets list but a footer alone must still show the rail
        render(
            <DateTimePicker
                value={VALUE}
                maxDate={MAX}
                onApply={jest.fn()}
                ranges={[]}
                rangesFooter={<span>Rolling input</span>}
            />
        )
        expect(screen.getByText('Rolling input')).toBeTruthy()
        expect(screen.queryByTitle('Last 7 days')).toBeNull()
    })

    it('renders only the vertical quick-ranges list with showCalendar={false}', () => {
        const ranges: DateTimeRange[] = [{ id: 1, name: 'This month', rangeSetter: (d) => d }]
        render(
            <DateTimePicker value={VALUE} maxDate={MAX} onApply={jest.fn()} ranges={ranges} showCalendar={false} />
        )

        expect(screen.getByTitle('This month')).toBeTruthy()
        expect(screen.queryByLabelText('Select Jan 10, 2023')).toBeNull()
    })

    it('applies both edges from a preset with an endSetter', async () => {
        const onApply = jest.fn()
        const lastMonth: DateTimeRange = {
            id: 1,
            name: 'Last month',
            rangeSetter: () => new Date(2022, 11, 1),
            endSetter: () => new Date(2022, 11, 31, 23, 59, 59),
        }
        render(<DateTimePicker value={VALUE} maxDate={MAX} onApply={onApply} ranges={[lastMonth]} />)

        await userEvent.click(screen.getByTitle('Last month'))
        await userEvent.click(screen.getByLabelText('Apply date range'))

        expect(onApply).toHaveBeenCalledTimes(1)
        const applied = onApply.mock.calls[0][0]
        expect(applied.start).toEqual(new Date(2022, 11, 1))
        expect(applied.end).toEqual(new Date(2022, 11, 31, 23, 59, 59))
        expect(applied.range).toBe(lastMonth)
    })
})
