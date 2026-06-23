import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'

import { DatePicker, DatePickerProps } from './DatePicker'

function polyfillPointerEventForBaseUI(): void {
    if (typeof window.PointerEvent === 'undefined') {
        window.PointerEvent = class extends MouseEvent {} as typeof window.PointerEvent
    }
}
polyfillPointerEventForBaseUI()

let mockQuillDatePickerFlag = false
jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => mockQuillDatePickerFlag,
}))

const QUILL_STUB_DATE = new Date(2023, 0, 20)
jest.mock('@posthog/quill-components', () => {
    const react = require('react')
    return {
        DatePicker: ({ onApply, onCancel }: { onApply: (value: Date) => void; onCancel: () => void }) =>
            react.createElement('div', null, [
                react.createElement('button', { key: 'apply', onClick: () => onApply(QUILL_STUB_DATE) }, 'stub-apply'),
                react.createElement('button', { key: 'cancel', onClick: onCancel }, 'stub-cancel'),
            ]),
    }
})

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
    beforeEach(() => {
        mockQuillDatePickerFlag = false
    })

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

    describe('when the QUILL_DATE_PICKER flag is enabled', () => {
        beforeEach(() => {
            mockQuillDatePickerFlag = true
        })

        it('renders the Quill trigger for the simple single-date case', () => {
            const { container } = renderDatePicker(dayjs('2023-01-15'))

            expect(container.querySelector('[data-quill]')).toBeTruthy()
            expect(within(container).getByText('January 15, 2023')).toBeTruthy()
        })

        it.each<[string, Partial<DatePickerProps>]>([
            ['granularity', { granularity: 'minute' }],
            ['selectionPeriod', { selectionPeriod: 'past' }],
            ['months', { months: 2 }],
        ])('falls back to LemonUI when %s is requested', (_name, props) => {
            const { container } = renderDatePicker(dayjs('2023-01-15'), props)

            expect(container.querySelector('[data-quill]')).toBeNull()
        })

        it('applying a date in the Quill panel calls onChange with a dayjs value', async () => {
            const { container, onChange } = renderDatePicker(dayjs('2023-01-15'))

            await userEvent.click(within(container).getByText('January 15, 2023'))
            await userEvent.click(await screen.findByText('stub-apply'))

            expect(onChange).toHaveBeenCalledTimes(1)
            expect(onChange.mock.calls[0][0].format('YYYY-MM-DD')).toBe('2023-01-20')
        })

        it('clears to null via the trigger clear control when clearable', async () => {
            const { container, onChange } = renderDatePicker(dayjs('2023-01-15'), { clearable: true })

            await userEvent.click(within(container).getByLabelText('Clear'))

            expect(onChange).toHaveBeenCalledWith(null)
        })
    })
})
