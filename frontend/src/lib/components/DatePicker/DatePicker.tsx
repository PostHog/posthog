import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput, LemonCalendarSelectInputProps } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

/**
 * Design-system-agnostic single-date picker — the migration seam between the LemonUI
 * calendar family and Quill's DateTimePicker. Callers depend on this dayjs-facing API;
 * the internal rendering swaps from LemonUI to Quill in one place without touching callers.
 *
 * Trigger concerns (placeholder, clearable, format, ...) live here by design — Quill
 * separates the trigger from the picker panel, so the wrapper owns the trigger.
 */
export interface DatePickerProps {
    value: dayjs.Dayjs | null
    onChange: (value: dayjs.Dayjs | null) => void
    /** Precision of the selected value. */
    granularity?: 'day' | 'hour' | 'minute'
    /** Restrict selectable dates relative to now. */
    selectionPeriod?: 'past' | 'upcoming'
    /** Timezone used to decide which past/upcoming dates are selectable (defaults to browser local). */
    selectionPeriodTimezone?: string
    /** Offer an "Include time?" toggle that flips granularity between day and minute. */
    showTimeToggle?: boolean
    onToggleTime?: (includeTime: boolean) => void
    /** Use 24-hour time entry instead of 12-hour with AM/PM. */
    use24HourFormat?: boolean
    /** Number of calendar months to render side by side. */
    months?: number
    /** Placeholder shown on the trigger when no value is set. */
    placeholder?: string
    /** Show a clear affordance on the trigger to reset the value to null. */
    clearable?: boolean
    /** dayjs format string for the trigger label. */
    format?: string
    /** Stretch the trigger to fill its container. */
    fullWidth?: boolean
    /** Disable the trigger and explain why on hover. */
    disabledReason?: string
    /** Externally control popover visibility. */
    visible?: boolean
    onClickOutside?: () => void
    'data-attr'?: string
}

export function DatePicker({
    value,
    onChange,
    granularity,
    selectionPeriod,
    selectionPeriodTimezone,
    showTimeToggle,
    onToggleTime,
    use24HourFormat,
    months,
    placeholder,
    clearable,
    format,
    fullWidth,
    disabledReason,
    visible,
    onClickOutside,
    'data-attr': dataAttr,
}: DatePickerProps): JSX.Element {
    // Only forward defined trigger props — the wrapped trigger hardcodes some defaults
    // (e.g. fullWidth) that an explicit `undefined` would clobber when spread.
    const buttonProps: NonNullable<LemonCalendarSelectInputProps['buttonProps']> = {}
    if (fullWidth !== undefined) {
        buttonProps.fullWidth = fullWidth
    }
    if (disabledReason !== undefined) {
        buttonProps.disabledReason = disabledReason
    }
    if (dataAttr !== undefined) {
        buttonProps['data-attr'] = dataAttr
    }

    return (
        <LemonCalendarSelectInput
            value={value}
            onChange={onChange}
            granularity={granularity}
            selectionPeriod={selectionPeriod}
            selectionPeriodTimezone={selectionPeriodTimezone}
            showTimeToggle={showTimeToggle}
            onToggleTime={onToggleTime}
            use24HourFormat={use24HourFormat}
            months={months}
            placeholder={placeholder}
            clearable={clearable}
            format={format}
            visible={visible}
            onClickOutside={onClickOutside}
            buttonProps={buttonProps}
        />
    )
}
