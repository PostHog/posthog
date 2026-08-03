import '@testing-library/jest-dom'

import { render, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarRange } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRange'

import { getByDataAttr } from '~/test/byDataAttr'

/** The leftmost month's title renders as a month + year jump `LemonSelect` pair, not plain text. */
function leftmostMonthYearLabel(container: HTMLElement): string {
    const month = getByDataAttr(container, 'lemon-calendar-month-select').textContent
    const year = getByDataAttr(container, 'lemon-calendar-year-select').textContent
    return `${month} ${year}`
}

describe('LemonCalendarRange', () => {
    test('shows time toggle when showTimeToggle is true', async () => {
        const onToggleTime = jest.fn()
        const { container } = render(
            <LemonCalendarRange
                months={1}
                value={[dayjs('2022-02-10'), dayjs('2022-02-28')]}
                onChange={jest.fn()}
                showTimeToggle
                onToggleTime={onToggleTime}
            />
        )

        const toggle = within(container).getByRole('switch')
        expect(toggle).toBeInTheDocument()
        expect(within(container).getByText('Include time?')).toBeInTheDocument()

        await userEvent.click(toggle)
        expect(onToggleTime).toHaveBeenCalledWith(true)
    })

    test('does not show time toggle by default', () => {
        const { container } = render(
            <LemonCalendarRange months={1} value={[dayjs('2022-02-10'), dayjs('2022-02-28')]} onChange={jest.fn()} />
        )

        expect(within(container).queryByRole('switch')).not.toBeInTheDocument()
        expect(within(container).queryByText('Include time?')).not.toBeInTheDocument()
    })

    test('select various ranges', async () => {
        const onClose = jest.fn()
        const onChange = jest.fn()

        function TestRange(): JSX.Element {
            const [value, setValue] = useState([dayjs('2022-02-10'), dayjs('2022-02-28')] as [dayjs.Dayjs, dayjs.Dayjs])
            return (
                <LemonCalendarRange
                    months={1}
                    value={value}
                    onClose={onClose}
                    onChange={(value) => {
                        setValue(value)
                        onChange(value)
                    }}
                />
            )
        }
        const { container } = render(<TestRange />)

        // find just one month
        const calendar = getByDataAttr(container, 'lemon-calendar')
        expect(calendar).toBeTruthy()

        // find February 2022
        expect(leftmostMonthYearLabel(calendar)).toBe('February 2022')

        async function clickOn(day: string): Promise<void> {
            await userEvent.click(await within(container).findByText(day))
            await userEvent.click(getByDataAttr(container, 'lemon-calendar-range-apply'))
        }

        // clicking inside the existing range (10-28) starts a fresh single-day selection at 15,
        // rather than dragging the start edge to 15 while keeping the old end
        await clickOn('15')
        expect(onChange).toHaveBeenCalledWith([dayjs('2022-02-15'), dayjs('2022-02-15T23:59:59.999Z')])

        // clicking after the current single day extends the range forward
        await clickOn('20')
        expect(onChange).toHaveBeenCalledWith([dayjs('2022-02-15'), dayjs('2022-02-20T23:59:59.999Z')])

        // clicking before the range start extends it backward
        await clickOn('8')
        expect(onChange).toHaveBeenCalledWith([dayjs('2022-02-08'), dayjs('2022-02-20T23:59:59.999Z')])

        // clicking exactly on a boundary collapses the range to that single day
        await clickOn('8')
        expect(onChange).toHaveBeenCalledWith([dayjs('2022-02-08'), dayjs('2022-02-08T23:59:59.999Z')])

        // clicking after the current single day extends the range forward again
        await clickOn('25')
        expect(onChange).toHaveBeenCalledWith([dayjs('2022-02-08'), dayjs('2022-02-25T23:59:59.999Z')])

        await userEvent.click(getByDataAttr(container, 'lemon-calendar-range-cancel'))
        expect(onClose).toHaveBeenCalled()
    })
})
