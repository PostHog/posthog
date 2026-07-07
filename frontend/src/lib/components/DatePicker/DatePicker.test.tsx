import { cleanup, render, screen, within } from '@testing-library/react'
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
const mockQuillPanelProps: { maxDate?: Date; showTime?: boolean; showTimeToggle?: boolean } = {}
jest.mock('@posthog/quill', () => {
    const react = require('react')
    return {
        ...jest.requireActual('@posthog/quill'),
        DatePicker: ({
            onApply,
            onCancel,
            onIncludeTimeChange,
            maxDate,
            showTime,
            showTimeToggle,
        }: {
            onApply: (value: Date) => void
            onCancel: () => void
            onIncludeTimeChange?: (includeTime: boolean) => void
            maxDate?: Date
            showTime?: boolean
            showTimeToggle?: boolean
        }) => {
            mockQuillPanelProps.maxDate = maxDate
            mockQuillPanelProps.showTime = showTime
            mockQuillPanelProps.showTimeToggle = showTimeToggle
            return react.createElement('div', null, [
                react.createElement('button', { key: 'apply', onClick: () => onApply(QUILL_STUB_DATE) }, 'stub-apply'),
                react.createElement('button', { key: 'cancel', onClick: onCancel }, 'stub-cancel'),
                react.createElement(
                    'button',
                    { key: 'time-on', onClick: () => onIncludeTimeChange?.(true) },
                    'stub-time-on'
                ),
            ])
        },
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
    afterEach(cleanup)

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
        await userEvent.click(await screen.findByRole('button', { name: '20' })) // nosemgrep: jest-no-byrole-name-queries
        await userEvent.click(screen.getByRole('button', { name: 'Apply' })) // nosemgrep: jest-no-byrole-name-queries

        expect(onChange).toHaveBeenCalledTimes(1)
        expect(onChange.mock.calls[0][0].format('YYYY-MM-DD')).toBe('2023-01-20')
    })

    it('clearing resets the value to null when clearable', async () => {
        const { container, onChange } = renderDatePicker(dayjs('2023-01-15'), { clearable: true })

        await userEvent.click(within(container).getByLabelText('Clear date'))

        expect(onChange).toHaveBeenCalledWith(null)
    })

    it.each<[string, Partial<DatePickerProps>, string]>([
        // No explicit type must keep LemonCalendarSelectInput's `secondary` trigger default rather than
        // clobbering it with `type: undefined` (which would fall back to LemonButton's tertiary default).
        ['no type keeps the secondary default', {}, 'LemonButton--secondary'],
        ['type primary maps through', { type: 'primary' }, 'LemonButton--primary'],
        ['type tertiary maps through', { type: 'tertiary' }, 'LemonButton--tertiary'],
        ['size small maps through', { size: 'small' }, 'LemonButton--small'],
        ['custom className forwards through', { className: 'bg-bg-light' }, 'bg-bg-light'],
    ])('maps trigger %s onto the LemonUI button', (_name, props, expectedClass) => {
        const { container } = renderDatePicker(dayjs('2023-01-15'), props)

        expect(container.querySelector('.LemonButton')?.className).toContain(expectedClass)
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

        it.each<[string, Partial<DatePickerProps>, string]>([
            ['size xsmall -> xs', { size: 'xsmall' }, 'quill-button--size-xs'],
            ['size small -> sm', { size: 'small' }, 'quill-button--size-sm'],
            ['size medium -> default', { size: 'medium' }, 'quill-button--size-default'],
            ['size large -> lg', { size: 'large' }, 'quill-button--size-lg'],
            ['type primary -> primary variant', { type: 'primary' }, 'quill-button--variant-primary'],
            ['type secondary -> outline variant', { type: 'secondary' }, 'quill-button--variant-outline'],
            ['type tertiary -> default variant', { type: 'tertiary' }, 'quill-button--variant-default'],
            ['no type -> outline variant', {}, 'quill-button--variant-outline'],
            ['no size -> default size', {}, 'quill-button--size-default'],
            ['custom className', { className: 'bg-bg-light' }, 'bg-bg-light'],
        ])('maps trigger %s onto the Quill button', (_name, props, expectedClass) => {
            const { container } = renderDatePicker(dayjs('2023-01-15'), props)

            expect(container.querySelector('[data-quill]')?.className).toContain(expectedClass)
        })

        it.each<[string, Partial<DatePickerProps>]>([
            ['hour granularity', { granularity: 'hour' }],
            ['12-hour time', { granularity: 'minute', use24HourFormat: false }],
            ['selectionPeriod', { selectionPeriod: 'past' }],
            ['months', { months: 2 }],
        ])('falls back to LemonUI when %s is requested', (_name, props) => {
            const { container } = renderDatePicker(dayjs('2023-01-15'), props)

            expect(container.querySelector('[data-quill]')).toBeNull()
        })

        it('renders minute granularity in Quill with a time-bearing label', () => {
            const { container } = renderDatePicker(dayjs('2023-01-15T09:30'), { granularity: 'minute' })

            expect(container.querySelector('[data-quill]')).toBeTruthy()
            expect(within(container).getByText('January 15, 2023 09:30')).toBeTruthy()
        })

        it.each<[string, Partial<DatePickerProps>, boolean, boolean]>([
            ['fixed minute (no toggle)', { granularity: 'minute' }, true, false],
            ['day with toggle', { granularity: 'day', showTimeToggle: true }, false, true],
            ['minute with toggle', { granularity: 'minute', showTimeToggle: true }, true, true],
        ])('maps %s onto the Quill panel time props', async (_name, props, showTime, showTimeToggle) => {
            const { container } = renderDatePicker(dayjs('2023-01-15'), props)

            await userEvent.click(within(container).getByRole('button', { name: /January 15, 2023/ })) // nosemgrep: jest-no-byrole-name-queries

            expect(mockQuillPanelProps.showTime).toBe(showTime)
            expect(mockQuillPanelProps.showTimeToggle).toBe(showTimeToggle)
        })

        it('applying a date in the Quill panel calls onChange with a dayjs value', async () => {
            const { container, onChange } = renderDatePicker(dayjs('2023-01-15'))

            await userEvent.click(within(container).getByText('January 15, 2023'))
            await userEvent.click(await screen.findByText('stub-apply'))

            expect(onChange).toHaveBeenCalledTimes(1)
            expect(onChange.mock.calls[0][0].format('YYYY-MM-DD')).toBe('2023-01-20')
        })

        it('updates the trigger label when time is toggled on in the panel', async () => {
            const { container } = renderDatePicker(dayjs('2023-01-15T09:30'), {
                granularity: 'day',
                showTimeToggle: true,
            })

            const trigger = within(container).getByRole('button', { name: /January 15, 2023/ }) // nosemgrep: jest-no-byrole-name-queries
            expect(trigger.textContent).toBe('January 15, 2023')

            await userEvent.click(trigger)
            await userEvent.click(await screen.findByText('stub-time-on'))

            const updatedTrigger = within(container).getByRole('button', { name: /January 15, 2023/ }) // nosemgrep: jest-no-byrole-name-queries
            expect(updatedTrigger.textContent).toBe('January 15, 2023 09:30')
            expect(mockQuillPanelProps.showTime).toBe(true)
        })

        it('forwards maxDate to the Quill panel so future dates can be selected', async () => {
            const max = dayjs('2024-01-15')
            const { container } = renderDatePicker(dayjs('2023-01-15'), { maxDate: max })

            await userEvent.click(within(container).getByText('January 15, 2023'))
            await screen.findByText('stub-apply')

            expect(mockQuillPanelProps.maxDate?.getTime()).toBe(max.toDate().getTime())
        })

        it('clears to null via the trigger clear control when clearable', async () => {
            const { container, onChange } = renderDatePicker(dayjs('2023-01-15'), { clearable: true })

            await userEvent.click(within(container).getByLabelText('Clear date'))

            expect(onChange).toHaveBeenCalledWith(null)
        })
    })
})
