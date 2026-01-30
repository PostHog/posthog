import '@testing-library/jest-dom'
import { render, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarRange } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRange'

import { getByDataAttr } from '~/test/byDataAttr'

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

        userEvent.click(toggle)
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
        expect(await within(calendar).findByText('February 2022')).toBeTruthy()

        async function clickOn(day: string): Promise<void> {
            userEvent.click(await within(container).findByText(day))
            userEvent.click(getByDataAttr(container, 'lemon-calendar-range-apply'))
        }

        // click on 15
        await clickOn('15')
        expect(onChange).toHaveBeenCalledWith([dayjs('2022-02-15'), dayjs('2022-02-28T23:59:59.999Z')])

        // click on 27
        await clickOn('27')
        expect(onChange).toHaveBeenCalledWith([dayjs('2022-02-15'), dayjs('2022-02-27T23:59:59.999Z')])

        // click on 16
        await clickOn('16')
        expect(onChange).toHaveBeenCalledWith([dayjs('2022-02-16'), dayjs('2022-02-27T23:59:59.999Z')])

        // click on 26
        await clickOn('26')
        expect(onChange).toHaveBeenCalledWith([dayjs('2022-02-16'), dayjs('2022-02-26T23:59:59.999Z')])

        // click on 10
        await clickOn('10')
        expect(onChange).toHaveBeenCalledWith([dayjs('2022-02-10'), dayjs('2022-02-26T23:59:59.999Z')])

        // click on 28
        await clickOn('28')
        expect(onChange).toHaveBeenCalledWith([dayjs('2022-02-10'), dayjs('2022-02-28T23:59:59.999Z')])

        // click on 20
        await clickOn('20')
        expect(onChange).toHaveBeenCalledWith([dayjs('2022-02-20'), dayjs('2022-02-28T23:59:59.999Z')])

        userEvent.click(getByDataAttr(container, 'lemon-calendar-range-cancel'))
        expect(onClose).toHaveBeenCalled()
    })
})
