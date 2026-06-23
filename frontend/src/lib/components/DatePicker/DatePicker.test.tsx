import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'

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
    it.each([
        ['the placeholder when there is no value', null, { placeholder: 'Pick a day' }, 'Pick a day'],
        ['the selected value with the default format', dayjs('2023-01-15'), {}, 'January 15, 2023'],
        ['the selected value with a custom format', dayjs('2023-01-15'), { format: 'YYYY-MM-DD' }, '2023-01-15'],
    ])('renders %s', (_name, value, props, expectedText) => {
        const { container } = renderDatePicker(value, props)
        expect(within(container).getByText(expectedText)).toBeTruthy()
    })

    it('selecting a date in the popover calls onChange', async () => {
        const { container, onChange } = renderDatePicker(dayjs('2023-01-15'))

        await userEvent.click(within(container).getByText('January 15, 2023'))
        // Accessible queries (role + name), not implementation-specific CSS classes / data-attrs,
        // so this survives the eventual swap of the backing calendar.
        await userEvent.click(await screen.findByRole('button', { name: '20' }))
        await userEvent.click(screen.getByRole('button', { name: 'Apply' }))

        expect(onChange).toHaveBeenCalledTimes(1)
        expect(onChange.mock.calls[0][0].format('YYYY-MM-DD')).toBe('2023-01-20')
    })

    it('clearing resets the value to null when clearable', async () => {
        const { container, onChange } = renderDatePicker(dayjs('2023-01-15'), { clearable: true })

        await userEvent.click(within(container).getByLabelText('Clear date'))

        expect(onChange).toHaveBeenCalledWith(null)
    })
})
