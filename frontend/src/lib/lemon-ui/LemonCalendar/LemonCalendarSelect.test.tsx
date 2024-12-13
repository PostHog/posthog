import { render, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { dayjs } from 'lib/dayjs'
import { getTimeElement, LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { useState } from 'react'

import { getByDataAttr } from '~/test/byDataAttr'

import { GetLemonButtonTimePropsOpts } from './LemonCalendar'

describe('LemonCalendarSelect', () => {
    test('select various dates', async () => {
        const onClose = jest.fn()
        const onChange = jest.fn()

        function TestSelect(): JSX.Element {
            const [value, setValue] = useState(dayjs('2022-02-10'))
            return (
                <LemonCalendarSelect
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
        const { container } = render(<TestSelect />)

        // find just one month
        const calendar = getByDataAttr(container, 'lemon-calendar')
        expect(calendar).toBeDefined()

        // find February 2022
        expect(await within(calendar).findByText('February 2022')).toBeDefined()

        async function clickOn(day: string): Promise<void> {
            userEvent.click(await within(container).findByText(day))
            userEvent.click(getByDataAttr(container, 'lemon-calendar-select-apply'))
        }

        // click on 15
        await clickOn('15')
        expect(onChange).toHaveBeenCalledWith(dayjs('2022-02-15'))

        // click on 27
        await clickOn('27')
        expect(onChange).toHaveBeenCalledWith(dayjs('2022-02-27'))

        userEvent.click(getByDataAttr(container, 'lemon-calendar-select-cancel'))
        expect(onClose).toHaveBeenCalled()
    })

    test('select various times', async () => {
        const onClose = jest.fn()
        const onChange = jest.fn()
        window.HTMLElement.prototype.scrollIntoView = jest.fn()

        jest.useFakeTimers().setSystemTime(new Date('2023-01-10 17:22:08'))

        function TestSelect(): JSX.Element {
            const [value, setValue] = useState<dayjs.Dayjs | null>(null)
            return (
                <LemonCalendarSelect
                    months={1}
                    value={value}
                    onClose={onClose}
                    onChange={(value) => {
                        setValue(value)
                        onChange(value)
                    }}
                    granularity="minute"
                />
            )
        }
        const { container } = render(<TestSelect />)

        async function clickOnDate(day: string): Promise<void> {
            const element = container.querySelector('.LemonCalendar__month') as HTMLElement
            if (element) {
                userEvent.click(await within(element).findByText(day))
                userEvent.click(getByDataAttr(container, 'lemon-calendar-select-apply'))
            }
        }

        async function clickOnTime(props: GetLemonButtonTimePropsOpts): Promise<void> {
            const element = getTimeElement(container.querySelector('.LemonCalendar__time'), props)
            if (element) {
                userEvent.click(element)
                userEvent.click(getByDataAttr(container, 'lemon-calendar-select-apply'))
            }
        }

        // click on hour 8
        await clickOnDate('15')
        // sets the date to 15, hour and minutes to current time, and seconds to 0
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T17:22:00.000Z'))

        // click on minute 42
        await clickOnTime({ unit: 'm', value: 42 })
        // sets the minutes but leaves all other values unchanged
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T17:42:00.000Z'))

        // click on 'am'
        await clickOnTime({ unit: 'a', value: 'am' })
        // subtracts 12 hours from the time
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T05:42:00.000Z'))

        // click on hour 8
        await clickOnTime({ unit: 'h', value: 8 })
        // only changes the hour
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-15T08:42:00.000Z'))
    })

    test('only allow upcoming selection', async () => {
        const onClose = jest.fn()
        const onChange = jest.fn()
        window.HTMLElement.prototype.scrollIntoView = jest.fn()

        jest.useFakeTimers().setSystemTime(new Date('2023-01-10 17:22:08'))

        function TestSelect(): JSX.Element {
            const [value, setValue] = useState<dayjs.Dayjs | null>(null)
            return (
                <LemonCalendarSelect
                    months={1}
                    value={value}
                    onClose={onClose}
                    onChange={(value) => {
                        setValue(value)
                        onChange(value)
                    }}
                    granularity="minute"
                    selectionPeriod="upcoming"
                />
            )
        }
        const { container } = render(<TestSelect />)

        async function clickOnDate(day: string): Promise<void> {
            const element = container.querySelector('.LemonCalendar__month') as HTMLElement
            if (element) {
                userEvent.click(await within(element).findByText(day))
                userEvent.click(getByDataAttr(container, 'lemon-calendar-select-apply'))
            }
        }

        async function clickOnTime(props: GetLemonButtonTimePropsOpts): Promise<void> {
            const element = getTimeElement(container.querySelector('.LemonCalendar__time'), props)
            if (element) {
                userEvent.click(element)
                userEvent.click(getByDataAttr(container, 'lemon-calendar-select-apply'))
            }
        }

        // click on minute
        await clickOnTime({ unit: 'm', value: 42 })
        // time is disabled until a date is clicked
        expect(onChange).not.toHaveBeenCalled()

        // click on past date
        await clickOnDate('9')
        // cannot select a date in the past
        expect(onChange).not.toHaveBeenCalled()

        // click on current date
        await clickOnDate('10')
        // chooses the current date and sets the time to the current hour and minute
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-10T17:22:00.000Z'))

        // click on an earlier hour
        await clickOnTime({ unit: 'a', value: 'am' })
        // does not update the date because it is in the past
        expect(onChange).toHaveBeenLastCalledWith(dayjs('2023-01-10T17:22:00.000Z'))

        // click on a later hour
        await clickOnTime({ unit: 'h', value: '8' })
        // updates the hour to 8pm (later than 5pm)
        expect(onChange).toHaveBeenLastCalledWith(dayjs('2023-01-10T20:22:00.000Z'))
    })

    test('only allow past selection', async () => {
        const onClose = jest.fn()
        const onChange = jest.fn()
        window.HTMLElement.prototype.scrollIntoView = jest.fn()

        jest.useFakeTimers().setSystemTime(new Date('2023-01-10 17:22:08'))

        function TestSelect(): JSX.Element {
            const [value, setValue] = useState<dayjs.Dayjs | null>(null)
            return (
                <LemonCalendarSelect
                    months={1}
                    value={value}
                    onClose={onClose}
                    onChange={(value) => {
                        setValue(value)
                        onChange(value)
                    }}
                    granularity="minute"
                    selectionPeriod="past"
                />
            )
        }
        const { container } = render(<TestSelect />)

        async function clickOnDate(day: string): Promise<void> {
            const element = container.querySelector('.LemonCalendar__month') as HTMLElement
            if (element) {
                userEvent.click(await within(element).findByText(day))
                userEvent.click(getByDataAttr(container, 'lemon-calendar-select-apply'))
            }
        }

        async function clickOnTime(props: GetLemonButtonTimePropsOpts): Promise<void> {
            const element = getTimeElement(container.querySelector('.LemonCalendar__time'), props)
            if (element) {
                userEvent.click(element)
                userEvent.click(getByDataAttr(container, 'lemon-calendar-select-apply'))
            }
        }

        // click on minute
        await clickOnTime({ unit: 'm', value: 12 })
        // time is disabled until a date is clicked
        expect(onChange).not.toHaveBeenCalled()

        // click on future date
        await clickOnDate('11')
        // cannot select a date in the future
        expect(onChange).not.toHaveBeenCalled()

        // click on current date
        await clickOnDate('10')
        // chooses the current date and sets the time to the current hour and minute
        expect(onChange).toHaveBeenCalledWith(dayjs('2023-01-10T17:22:00.000Z'))

        // click on an later hour
        await clickOnTime({ unit: 'h', value: '18' })
        // does not update the date because it is in the future
        expect(onChange).toHaveBeenLastCalledWith(dayjs('2023-01-10T17:22:00.000Z'))

        // click on an earlier hour
        await clickOnTime({ unit: 'h', value: '2' })
        // updates the hour to 2pm (earlier than 5pm)
        expect(onChange).toHaveBeenLastCalledWith(dayjs('2023-01-10T14:22:00.000Z'))
    })
})
