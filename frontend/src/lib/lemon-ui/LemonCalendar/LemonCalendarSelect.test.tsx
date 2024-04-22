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
                    showTime
                />
            )
        }
        const { container } = render(<TestSelect />)

        async function clickOn(props: GetLemonButtonTimePropsOpts): Promise<void> {
            const element = getTimeElement(container, props)
            if (element) {
                userEvent.click(element)
                userEvent.click(getByDataAttr(container, 'lemon-calendar-select-apply'))
            }
        }

        // click on hour 8
        await clickOn({ unit: 'h', value: 8 })
        expect(onChange).toHaveBeenCalledWith(dayjs('2024-04-22T08:00:00.000Z'))
        // scrolls to both the hour and minute as date was previously set
        expect(window.HTMLElement.prototype.scrollIntoView).toHaveBeenCalledTimes(2)

        // click on minute 42
        await clickOn({ unit: 'm', value: 42 })
        expect(onChange).toHaveBeenCalledWith(dayjs('2024-04-22T08:42:00.000Z'))
        // scrolls to the new minute, hour does not scroll because it is already set
        expect(window.HTMLElement.prototype.scrollIntoView).toHaveBeenCalledTimes(3)

        // click on 'pm'
        await clickOn({ unit: 'a', value: 'pm' })
        expect(onChange).toHaveBeenCalledWith(dayjs('2024-04-22T20:42:00.000Z'))
        // no scrolls
        expect(window.HTMLElement.prototype.scrollIntoView).toHaveBeenCalledTimes(3)
    })
})
