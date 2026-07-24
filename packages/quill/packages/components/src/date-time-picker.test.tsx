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

    it('presetsFirst: a preset click applies immediately without the Apply button', async () => {
        const onApply = jest.fn()
        const lastMonth: DateTimeRange = {
            id: 1,
            name: 'Last month',
            rangeSetter: () => new Date(2022, 11, 1),
            endSetter: () => new Date(2022, 11, 31, 23, 59, 59),
        }
        render(<DateTimePicker value={VALUE} maxDate={MAX} onApply={onApply} ranges={[lastMonth]} presetsFirst />)

        await userEvent.click(screen.getByTitle('Last month'))

        expect(onApply).toHaveBeenCalledTimes(1)
        const applied = onApply.mock.calls[0][0]
        expect(applied.start).toEqual(new Date(2022, 11, 1))
        expect(applied.end).toEqual(new Date(2022, 11, 31, 23, 59, 59))
        expect(applied.range).toBe(lastMonth)
    })

    it('presetsFirst: the calendar is collapsed until Custom range, Cancel collapses it back, footerExtra persists', async () => {
        const ranges: DateTimeRange[] = [{ id: 1, name: 'This month', rangeSetter: (d) => d }]
        const presetValue = { start: VALUE.start, end: VALUE.end, range: ranges[0] }
        render(
            <DateTimePicker
                value={presetValue}
                maxDate={MAX}
                onApply={jest.fn()}
                ranges={ranges}
                presetsFirst
                footerExtra={<span>Exclusions</span>}
            />
        )

        expect(screen.queryByLabelText('Apply date range')).toBeNull()
        expect(screen.getByText('Exclusions')).toBeTruthy()

        await userEvent.click(screen.getByText('Custom range…'))
        expect(screen.getByLabelText('Apply date range')).toBeTruthy()
        expect(screen.getByText('Exclusions')).toBeTruthy()

        await userEvent.click(screen.getByLabelText('Cancel'))
        expect(screen.queryByLabelText('Apply date range')).toBeNull()
    })

    it('presetsFirst: opens expanded when the value is a custom range', () => {
        render(
            <DateTimePicker
                value={VALUE}
                maxDate={MAX}
                onApply={jest.fn()}
                ranges={[{ id: 1, name: 'This month', rangeSetter: (d) => d }]}
                presetsFirst
            />
        )

        expect(screen.getByLabelText('Apply date range')).toBeTruthy()
    })
})
