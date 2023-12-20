import { render, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { useState } from 'react'

import { getByDataAttr } from '~/test/byDataAttr'

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
})
