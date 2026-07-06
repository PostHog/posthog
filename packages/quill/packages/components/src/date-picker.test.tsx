import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

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

        // nosemgrep: jest-no-byrole-name-queries — small DOM, asserts accessibility contract of the toggle
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

        expect(!!screen.queryByRole('switch', { name: 'Include time' })).toBe(expected) // nosemgrep: jest-no-byrole-name-queries — small DOM, asserts accessibility contract of the toggle
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

        await userEvent.click(screen.getByRole('switch', { name: 'Include time' })) // nosemgrep: jest-no-byrole-name-queries — small DOM, asserts accessibility contract of the toggle

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
})
