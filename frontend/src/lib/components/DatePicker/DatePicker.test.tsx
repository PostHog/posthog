import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { dayjs, dayjsNowInTimezone } from 'lib/dayjs'

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
const mockQuillPanelProps: {
    minDate?: Date
    maxDate?: Date
    showTime?: boolean
    showTimeToggle?: boolean
    hourCycle?: 12 | 24
    weekStartsOn?: number
} = {}
jest.mock('@posthog/quill', () => {
    const react = require('react')
    return {
        ...jest.requireActual('@posthog/quill'),
        DatePicker: ({
            onApply,
            onCancel,
            onIncludeTimeChange,
            minDate,
            maxDate,
            showTime,
            showTimeToggle,
            hourCycle,
            weekStartsOn,
        }: {
            onApply: (value: Date) => void
            onCancel: () => void
            onIncludeTimeChange?: (includeTime: boolean) => void
            minDate?: Date
            maxDate?: Date
            showTime?: boolean
            showTimeToggle?: boolean
            hourCycle?: 12 | 24
            weekStartsOn?: number
        }) => {
            mockQuillPanelProps.minDate = minDate
            mockQuillPanelProps.maxDate = maxDate
            mockQuillPanelProps.showTime = showTime
            mockQuillPanelProps.showTimeToggle = showTimeToggle
            mockQuillPanelProps.hourCycle = hourCycle
            mockQuillPanelProps.weekStartsOn = weekStartsOn
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

        it('renders minute granularity in Quill with a time-bearing label', () => {
            const { container } = renderDatePicker(dayjs('2023-01-15T09:30'), { granularity: 'minute' })

            expect(container.querySelector('[data-quill]')).toBeTruthy()
            expect(within(container).getByText('January 15, 2023 9:30 AM')).toBeTruthy()
        })

        it.each<[string, Partial<DatePickerProps>, 12 | 24]>([
            // LemonUI's default is 12-hour with AM/PM, so an unset prop must stay 12-hour under Quill too.
            ['unset use24HourFormat -> 12-hour entry', { granularity: 'minute' }, 12],
            ['use24HourFormat -> 24-hour entry', { granularity: 'minute', use24HourFormat: true }, 24],
        ])('maps %s onto the Quill panel', async (_name, props, hourCycle) => {
            const { container } = renderDatePicker(dayjs('2023-01-15T09:30'), props)

            await userEvent.click(container.querySelector('[data-quill]') as HTMLElement)
            await screen.findByText('stub-apply')

            expect(mockQuillPanelProps.hourCycle).toBe(hourCycle)
        })

        it.each<[string, DatePickerProps['selectionPeriod'], 'minDate' | 'maxDate', 'minDate' | 'maxDate']>([
            ['upcoming bounds below by now', 'upcoming', 'minDate', 'maxDate'],
            ['past bounds above by now', 'past', 'maxDate', 'minDate'],
        ])('selectionPeriod %s', async (_name, selectionPeriod, boundedSide, openSide) => {
            const { container } = renderDatePicker(dayjs('2023-01-15'), { selectionPeriod })

            await userEvent.click(container.querySelector('[data-quill]') as HTMLElement)
            await screen.findByText('stub-apply')

            const bound = mockQuillPanelProps[boundedSide]
            expect(bound).toBeInstanceOf(Date)
            expect(Math.abs((bound as Date).getTime() - Date.now())).toBeLessThan(5000)
            expect(mockQuillPanelProps[openSide]).toBeUndefined()
        })

        it('evaluates selection bounds in the selection timezone, not browser-local time', async () => {
            // UTC+14 with no DST — differs from any realistic CI timezone, so ignoring the
            // timezone (falling back to local "now") shows up as an hours-wide mismatch.
            const timezone = 'Pacific/Kiritimati'
            const { container } = renderDatePicker(dayjs('2023-01-15'), {
                selectionPeriod: 'upcoming',
                selectionPeriodTimezone: timezone,
            })

            await userEvent.click(container.querySelector('[data-quill]') as HTMLElement)
            await screen.findByText('stub-apply')

            const expected = dayjsNowInTimezone(timezone).toDate().getTime()
            expect(Math.abs((mockQuillPanelProps.minDate as Date).getTime() - expected)).toBeLessThan(5000)
        })

        it('passes the team week start to the Quill panel', async () => {
            const { container } = renderDatePicker(dayjs('2023-01-15'))

            await userEvent.click(container.querySelector('[data-quill]') as HTMLElement)
            await screen.findByText('stub-apply')

            // teamLogic's default in tests is 0 (Sunday); the contract is that the prop is wired, not undefined.
            expect(mockQuillPanelProps.weekStartsOn).toBe(0)
        })

        it('supports the controlled visibility trio', async () => {
            const onOpen = jest.fn()
            const onClose = jest.fn()

            const { rerender } = render(
                <DatePicker
                    value={dayjs('2023-01-15')}
                    onChange={jest.fn()}
                    visible={false}
                    onOpen={onOpen}
                    onClose={onClose}
                />
            )

            expect(screen.queryByText('stub-apply')).toBeNull()
            await userEvent.click(screen.getByText('January 15, 2023'))
            expect(onOpen).toHaveBeenCalledTimes(1)
            // The panel only opens once the caller flips `visible` — the trigger click alone must not open it.
            expect(screen.queryByText('stub-apply')).toBeNull()

            rerender(
                <DatePicker
                    value={dayjs('2023-01-15')}
                    onChange={jest.fn()}
                    visible={true}
                    onOpen={onOpen}
                    onClose={onClose}
                />
            )

            await userEvent.click(await screen.findByText('stub-cancel'))
            expect(onClose).toHaveBeenCalledTimes(1)
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
            expect(updatedTrigger.textContent).toBe('January 15, 2023 9:30 AM')
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
