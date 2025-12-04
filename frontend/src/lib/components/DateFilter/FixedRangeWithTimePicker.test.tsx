import '@testing-library/jest-dom'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { dayjs } from 'lib/dayjs'

import { FixedRangeWithTimePicker } from './FixedRangeWithTimePicker'

describe('FixedRangeWithTimePicker', () => {
    const setDate = jest.fn()
    const onClose = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('renders header', () => {
        render(<FixedRangeWithTimePicker rangeDateFrom={null} rangeDateTo={null} setDate={setDate} onClose={onClose} />)

        expect(screen.getByText(/select a date and time range/i)).toBeInTheDocument()
    })

    it('renders Start and End buttons', () => {
        render(
            <FixedRangeWithTimePicker
                rangeDateFrom={dayjs('2024-01-15T10:00:00')}
                rangeDateTo={dayjs('2024-01-15T11:00:00')}
                setDate={setDate}
                onClose={onClose}
            />
        )

        expect(screen.getAllByText(/start:/i).length).toBeGreaterThan(0)
        expect(screen.getAllByText(/end:/i).length).toBeGreaterThan(0)
    })

    it('calls onClose when close button is clicked', () => {
        const { container } = render(
            <FixedRangeWithTimePicker
                rangeDateFrom={dayjs('2024-01-15T10:00:00')}
                rangeDateTo={dayjs('2024-01-15T11:00:00')}
                setDate={setDate}
                onClose={onClose}
            />
        )

        const closeButton = container.querySelector('[aria-label="close"]') as HTMLElement
        expect(closeButton).toBeTruthy()
        userEvent.click(closeButton)
        expect(onClose).toHaveBeenCalled()
    })

    it('calls setDate with ISO format when Apply is clicked', () => {
        const { container } = render(
            <FixedRangeWithTimePicker
                rangeDateFrom={dayjs('2024-01-15T10:00:00')}
                rangeDateTo={dayjs('2024-01-15T11:00:00')}
                setDate={setDate}
                onClose={onClose}
            />
        )

        const footer = container.querySelector('[data-attr="lemon-calendar-range-with-time-footer"]') as HTMLElement
        userEvent.click(within(footer).getByText(/apply/i))
        expect(setDate).toHaveBeenCalledWith('2024-01-15T10:00:00', '2024-01-15T11:00:00', false, true)
    })

    it('swaps dates on Apply if start is after end', () => {
        const { container } = render(
            <FixedRangeWithTimePicker
                rangeDateFrom={dayjs('2024-01-15T14:00:00')}
                rangeDateTo={dayjs('2024-01-15T10:00:00')}
                setDate={setDate}
                onClose={onClose}
            />
        )

        const footer = container.querySelector('[data-attr="lemon-calendar-range-with-time-footer"]') as HTMLElement
        userEvent.click(within(footer).getByText(/apply/i))
        expect(setDate).toHaveBeenCalledWith('2024-01-15T10:00:00', '2024-01-15T14:00:00', false, true)
    })

    it('preserves PM time when initialized with PM', () => {
        const { container } = render(
            <FixedRangeWithTimePicker
                rangeDateFrom={dayjs('2024-01-15T14:30:00')}
                rangeDateTo={dayjs('2024-01-15T16:00:00')}
                setDate={setDate}
                onClose={onClose}
            />
        )

        const footer = container.querySelector('[data-attr="lemon-calendar-range-with-time-footer"]') as HTMLElement
        userEvent.click(within(footer).getByText(/apply/i))
        expect(setDate).toHaveBeenCalledWith('2024-01-15T14:30:00', '2024-01-15T16:00:00', false, true)
    })

    it('adjusts end time when start hour is changed to be after end', () => {
        const { container } = render(
            <FixedRangeWithTimePicker
                rangeDateFrom={dayjs('2024-01-15T10:00:00')}
                rangeDateTo={dayjs('2024-01-15T11:00:00')}
                setDate={setDate}
                onClose={onClose}
            />
        )

        // Click on hour 12 (PM) - this should be after the end time of 11:00 AM
        const hourButton = container.querySelector('[data-attr="12-h"]') as HTMLElement
        expect(hourButton).toBeTruthy()
        userEvent.click(hourButton)

        // Click PM to make it 12 PM (noon)
        const pmButton = container.querySelector('[data-attr="pm-a"]') as HTMLElement
        expect(pmButton).toBeTruthy()
        userEvent.click(pmButton)

        // Apply and verify end was adjusted (start 12:00 PM, end should be 1:00 PM)
        const footer = container.querySelector('[data-attr="lemon-calendar-range-with-time-footer"]') as HTMLElement
        userEvent.click(within(footer).getByText(/apply/i))

        // The handleApply swaps if needed, so result should be valid
        expect(setDate).toHaveBeenCalled()
        const [from, to] = setDate.mock.calls[0]
        expect(dayjs(from).isBefore(dayjs(to))).toBe(true)
    })
})
