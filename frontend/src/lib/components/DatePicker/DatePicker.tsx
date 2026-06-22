import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput, LemonCalendarSelectInputProps } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

/**
 * Design-system-agnostic single-date picker — the migration seam between the LemonUI
 * calendar family and Quill's DateTimePicker. Callers depend on this dayjs-facing API;
 * the internal rendering swaps from LemonUI to Quill in one place without touching callers.
 * That swap should land behind a feature flag so LemonUI and Quill can run side by side
 * and roll back without a revert.
 *
 * Trigger concerns (placeholder, clearable, format, ...) live here by design — Quill
 * separates the trigger from the picker panel, so the wrapper owns the trigger.
 *
 * The prop surface is intentionally minimal: trigger-styling props (size, type) and
 * `selectionPeriodLimit` are deliberately omitted until a real caller needs them, rather
 * than re-exposing the wrapped component's full API and losing the decoupling.
 *
 * Controlled visibility is a full trio: pass `visible` plus `onOpen` (fired when the
 * trigger is clicked) and `onClickOutside` / `onClose` (fired when the panel dismisses) so
 * the caller can drive `visible` itself. Without `onOpen` a controlled picker can't be
 * opened from its own trigger.
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
    /** Stretch the trigger to fill its container. Defaults to true — the seam owns this default rather than inheriting it from the wrapped trigger. */
    fullWidth?: boolean
    /** Disable the trigger and explain why on hover. */
    disabledReason?: string
    /** Externally control popover visibility. Pair with `onOpen` + `onClickOutside`/`onClose`. */
    visible?: boolean
    /** Fired when the trigger is clicked — set your `visible` state to true here. */
    onOpen?: () => void
    /** Fired when the panel is dismissed by clicking outside it. */
    onClickOutside?: () => void
    /** Fired when the panel's Cancel/close control is used. */
    onClose?: () => void
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
    fullWidth = true,
    disabledReason,
    visible,
    onOpen,
    onClickOutside,
    onClose,
    'data-attr': dataAttr,
}: DatePickerProps): JSX.Element {
    const buttonProps: NonNullable<LemonCalendarSelectInputProps['buttonProps']> = {
        fullWidth,
        disabledReason,
        'data-attr': dataAttr,
    }
    // The wrapped trigger only flips its own uncontrolled state; a controlled caller needs the
    // click to drive their `visible`, so forward `onOpen` as the trigger's onClick when given.
    if (onOpen) {
        buttonProps.onClick = onOpen
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
            onClose={onClose}
            buttonProps={buttonProps}
        />
    )
}
