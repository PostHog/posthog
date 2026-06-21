import { render, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'

import { getByDataAttr } from '~/test/byDataAttr'

import { DatePicker, DatePickerProps } from './DatePicker'

const renderDatePicker = (
    initialValue: dayjs.Dayjs | null = null,
    props: Partial<DatePickerProps> = {}
): { container: HTMLElement; onChange: jest.Mock } => {
    const onChange = jest.fn()

    function Test(): JSX.Element {
        const [value, setValue] = useState<dayjs.Dayjs | null>(initialValue)
        return (
            <DatePicker
                {...props}
                value={value}
                onChange={(next) => {
                    setValue(next)
                    onChange(next)
                }}
            />
        )
    }

    const { container } = render(<Test />)
    return { container, onChange }
}

describe('DatePicker', () => {
    it('shows the placeholder when there is no value', () => {
        const { container } = renderDatePicker(null, { placeholder: 'Pick a day' })
        expect(within(container).getByText('Pick a day')).toBeTruthy()
    })

    it('renders the selected value with the default format', () => {
        const { container } = renderDatePicker(dayjs('2023-01-15'))
        expect(within(container).getByText('January 15, 2023')).toBeTruthy()
    })

    it('renders the selected value with a custom format', () => {
        const { container } = renderDatePicker(dayjs('2023-01-15'), { format: 'YYYY-MM-DD' })
        expect(within(container).getByText('2023-01-15')).toBeTruthy()
    })

    it('selecting a date in the popover calls onChange', async () => {
        const { container, onChange } = renderDatePicker(dayjs('2023-01-15'))

        await userEvent.click(within(container).getByText('January 15, 2023'))
        const month = document.querySelector('.LemonCalendar__month') as HTMLElement
        await userEvent.click(within(month).getByText('20'))
        await userEvent.click(getByDataAttr(document.body, 'lemon-calendar-select-apply'))

        expect(onChange).toHaveBeenCalledTimes(1)
        expect(onChange.mock.calls[0][0].format('YYYY-MM-DD')).toBe('2023-01-20')
    })

    it('clearing resets the value to null when clearable', async () => {
        const { container, onChange } = renderDatePicker(dayjs('2023-01-15'), { clearable: true })

        await userEvent.click(within(container).getByLabelText('Clear date'))

        expect(onChange).toHaveBeenCalledWith(null)
    })
})
