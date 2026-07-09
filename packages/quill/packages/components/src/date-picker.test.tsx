import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { addYears, format, startOfDay } from 'date-fns'

import { DatePicker } from './date-picker'

// Base UI's Switch constructs PointerEvents, which jsdom doesn't implement.
if (typeof window.PointerEvent === 'undefined') {
    window.PointerEvent = class extends MouseEvent {} as typeof window.PointerEvent
}

const VALUE = new Date(2023, 0, 15, 10, 30) // 15 Jan 2023, 10:30
const MAX = new Date(2030, 0, 1)

describe('DatePicker', () => {
    afterEach(cleanup)

    it('applies a date-only value floored to the start of the day', async () => {
        const onApply = jest.fn()
        render(<DatePicker value={VALUE} maxDate={MAX} onApply={onApply} />)

        await userEvent.click(screen.getByLabelText('Select Jan 20, 2023'))
        await userEvent.click(screen.getByLabelText('Apply date'))

        expect(onApply).toHaveBeenCalledTimes(1)
        const applied: Date = onApply.mock.calls[0][0]
        expect([applied.getFullYear(), applied.getMonth(), applied.getDate()]).toEqual([2023, 0, 20])
        expect([applied.getHours(), applied.getMinutes()]).toEqual([0, 0])
    })

    it('keeps the time of day when showTime is on', async () => {
        const onApply = jest.fn()
        render(<DatePicker value={VALUE} maxDate={MAX} showTime onApply={onApply} />)

        await userEvent.click(screen.getByLabelText('Select Jan 20, 2023'))
        await userEvent.click(screen.getByLabelText('Apply date'))

        const applied: Date = onApply.mock.calls[0][0]
        expect([applied.getDate(), applied.getHours(), applied.getMinutes()]).toEqual([20, 10, 30])
    })

    it('re-floors to the start of the day when the time toggle is switched off', async () => {
        const onApply = jest.fn()
        render(<DatePicker value={VALUE} maxDate={MAX} showTime onApply={onApply} />)

        // nosemgrep: jest-no-byrole-name-queries - small DOM, asserts accessibility contract of the toggle
        await userEvent.click(screen.getByRole('switch', { name: 'Include time' })) // turn time off
        await userEvent.click(screen.getByLabelText('Apply date'))

        const applied: Date = onApply.mock.calls[0][0]
        expect([applied.getDate(), applied.getHours(), applied.getMinutes()]).toEqual([15, 0, 0])
    })

    it.each([
        ['off by default', {}, false],
        ['on when showTime is set', { showTime: true }, true],
        ['on when showTimeToggle is set without showTime', { showTimeToggle: true }, true],
        ['off when showTimeToggle is false despite showTime', { showTime: true, showTimeToggle: false }, false],
    ])('renders the include-time toggle %s', (_name, props, expected) => {
        render(<DatePicker value={VALUE} maxDate={MAX} onApply={jest.fn()} {...props} />)

        expect(!!screen.queryByRole('switch', { name: 'Include time' })).toBe(expected) // nosemgrep: jest-no-byrole-name-queries - small DOM, asserts accessibility contract of the toggle
    })

    it('keeps time with no toggle when showTimeToggle is false', async () => {
        const onApply = jest.fn()
        render(<DatePicker value={VALUE} maxDate={MAX} showTime showTimeToggle={false} onApply={onApply} />)

        await userEvent.click(screen.getByLabelText('Select Jan 20, 2023'))
        await userEvent.click(screen.getByLabelText('Apply date'))

        const applied: Date = onApply.mock.calls[0][0]
        expect([applied.getDate(), applied.getHours(), applied.getMinutes()]).toEqual([20, 10, 30])
    })

    it('reports toggle changes through onIncludeTimeChange', async () => {
        const onIncludeTimeChange = jest.fn()
        render(
            <DatePicker
                value={VALUE}
                maxDate={MAX}
                showTime
                onIncludeTimeChange={onIncludeTimeChange}
                onApply={jest.fn()}
            />
        )

        await userEvent.click(screen.getByRole('switch', { name: 'Include time' })) // nosemgrep: jest-no-byrole-name-queries - small DOM, asserts accessibility contract of the toggle

        expect(onIncludeTimeChange).toHaveBeenCalledWith(false)
    })

    it('disables calendar days before minDate', () => {
        render(<DatePicker value={VALUE} minDate={new Date(2023, 0, 10)} maxDate={MAX} onApply={jest.fn()} />)

        expect(screen.getByLabelText('Select Jan 5, 2023').getAttribute('aria-disabled')).toBe('true')
        expect(screen.getByLabelText('Select Jan 20, 2023').getAttribute('aria-disabled')).toBe('false')
    })

    it('calls onCancel without applying', async () => {
        const onApply = jest.fn()
        const onCancel = jest.fn()
        render(<DatePicker value={VALUE} maxDate={MAX} onApply={onApply} onCancel={onCancel} />)

        await userEvent.click(screen.getByLabelText('Cancel'))

        expect(onCancel).toHaveBeenCalledTimes(1)
        expect(onApply).not.toHaveBeenCalled()
    })

    it('renders a 12-hour clock and maps the AM/PM toggle back onto the 24-hour value', async () => {
        const onApply = jest.fn()
        render(<DatePicker value={new Date(2023, 0, 15, 15, 30)} maxDate={MAX} showTime hourCycle={12} onApply={onApply} />)

        // 15:30 displays as 03:30 PM (the aria-label sits on the NumberField root, not the input)
        expect((screen.getByLabelText('Hour').querySelector('input') as HTMLInputElement).value).toBe('03')
        await userEvent.click(screen.getByLabelText('Switch to AM'))
        // The segmented input debounces before committing; the footer reflects the committed value.
        await screen.findByText('01/15/23 3:30 AM')
        await userEvent.click(screen.getByLabelText('Apply date'))

        const applied: Date = onApply.mock.calls[0][0]
        expect([applied.getHours(), applied.getMinutes()]).toEqual([3, 30])
    })

    it('allows dates after today when no maxDate is given', async () => {
        const onApply = jest.fn()
        const futureDay = addYears(startOfDay(new Date()), 1)
        render(<DatePicker value={futureDay} onApply={onApply} />)

        const cell = screen.getByLabelText(`Select ${format(futureDay, 'PP')}`)
        expect(cell.getAttribute('aria-disabled')).toBe('false')
        await userEvent.click(cell)
        await userEvent.click(screen.getByLabelText('Apply date'))

        expect(onApply.mock.calls[0][0].getTime()).toBe(futureDay.getTime())
    })

    it('clamps an applied datetime that lands below minDate on the boundary day', async () => {
        const onApply = jest.fn()
        const min = new Date(2023, 0, 10, 12, 0)
        render(<DatePicker value={VALUE} minDate={min} maxDate={MAX} showTime onApply={onApply} />)

        // Jan 10 is selectable (day-granular calendar), but the carried-over 10:30 is before minDate's 12:00.
        await userEvent.click(screen.getByLabelText('Select Jan 10, 2023'))
        await userEvent.click(screen.getByLabelText('Apply date'))

        expect(onApply.mock.calls[0][0].getTime()).toBe(min.getTime())
    })
})
