import { useState } from 'react'

import { IconCalendar, IconX } from '@posthog/icons'
import { Button, cn, DatePicker as QuillDatePicker, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonCalendarSelectInput, LemonCalendarSelectInputProps } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

/**
 * Design-system-agnostic single-date picker — the migration seam between the LemonUI
 * calendar family and Quill's DateTimePicker. Callers depend on this dayjs-facing API;
 * the internal rendering swaps from LemonUI to Quill in one place without touching callers.
 *
 * The swap is gated by the `QUILL_DATE_PICKER` feature flag so LemonUI and Quill run side
 * by side and roll back without a revert. The Quill panel does not yet cover the whole
 * feature surface, so `quillCanRender` falls back to LemonUI whenever a request needs a
 * capability Quill is missing: hour-only granularity, 12-hour time entry, selection
 * windows, multi-month, or controlled visibility. Day/minute granularity (with an optional
 * include-time toggle) is handled; minute entry renders in 24-hour time. Each Quill panel
 * increment removes one fallback condition.
 *
 * Trigger concerns (placeholder, clearable, format, ...) live here by design — Quill
 * separates the trigger from the picker panel, so the wrapper owns the trigger.
 *
 * Trigger-styling props (`size`, `type`, `className`) are typed and decoupled — the seam
 * maps them onto whichever button backs the current renderer (LemonButton today, Quill
 * Button under the flag) rather than re-exposing a raw `buttonProps` pass-through.
 * `selectionPeriodLimit` stays omitted until a real caller needs it.
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
    /** Latest selectable date. Bounds the Quill panel; when omitted Quill caps at today, so future-date callers must pass this. The LemonUI fallback has no equivalent and stays unbounded above. */
    maxDate?: dayjs.Dayjs
    /** Placeholder shown on the trigger when no value is set. */
    placeholder?: string
    /** Show a clear affordance on the trigger to reset the value to null. */
    clearable?: boolean
    /** dayjs format string for the trigger label. */
    format?: string
    /** Stretch the trigger to fill its container. Defaults to true — the seam owns this default rather than inheriting it from the wrapped trigger. */
    fullWidth?: boolean
    /** Trigger button size. Mapped to the underlying button per backing renderer. */
    size?: 'xsmall' | 'small' | 'medium' | 'large'
    /** Trigger button style. Mapped to the underlying button per backing renderer (secondary -> Quill outline; primary -> primary; tertiary -> default). When unset, the Quill trigger uses its neutral `outline`. */
    type?: 'primary' | 'secondary' | 'tertiary'
    /** Extra class names merged onto the trigger. */
    className?: string
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

const QUILL_TRIGGER_FORMAT = 'MMMM D, YYYY'
const QUILL_TRIGGER_DATETIME_FORMAT = 'MMMM D, YYYY HH:mm'

const QUILL_TRIGGER_VARIANT: Record<NonNullable<DatePickerProps['type']>, 'primary' | 'outline' | 'default'> = {
    primary: 'primary',
    secondary: 'outline',
    tertiary: 'default',
}
const QUILL_TRIGGER_SIZE: Record<NonNullable<DatePickerProps['size']>, 'default' | 'xs' | 'sm' | 'lg'> = {
    xsmall: 'xs',
    small: 'sm',
    medium: 'default',
    large: 'lg',
}

function quillCanRender(props: DatePickerProps): boolean {
    return (
        props.granularity !== 'hour' &&
        props.use24HourFormat !== false &&
        props.selectionPeriod === undefined &&
        props.months === undefined &&
        props.visible === undefined &&
        props.onOpen === undefined &&
        props.onClickOutside === undefined &&
        props.onClose === undefined
    )
}

export function DatePicker(props: DatePickerProps): JSX.Element {
    const quillEnabled = useFeatureFlag('QUILL_DATE_PICKER')
    if (quillEnabled && quillCanRender(props)) {
        return <DatePickerQuill {...props} />
    }
    return <DatePickerLemon {...props} />
}

function DatePickerQuill({
    value,
    onChange,
    granularity,
    showTimeToggle,
    onToggleTime,
    placeholder,
    clearable,
    format,
    fullWidth = true,
    size,
    type,
    className,
    disabledReason,
    maxDate,
    'data-attr': dataAttr,
}: DatePickerProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const [includeTime, setIncludeTime] = useState(granularity === 'minute')
    const labelFormat = format ?? (includeTime ? QUILL_TRIGGER_DATETIME_FORMAT : QUILL_TRIGGER_FORMAT)
    const label = value ? value.format(labelFormat) : (placeholder ?? 'Select date')

    const handleIncludeTimeChange = (next: boolean): void => {
        setIncludeTime(next)
        onToggleTime?.(next)
    }

    const applyDate = (next: Date): void => {
        onChange(dayjs(next))
        setOpen(false)
    }

    return (
        <div className={fullWidth ? 'flex w-full items-center gap-1' : 'flex items-center gap-1'}>
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger
                    render={
                        <Button
                            variant={type ? QUILL_TRIGGER_VARIANT[type] : 'outline'}
                            size={size ? QUILL_TRIGGER_SIZE[size] : 'default'}
                            data-attr={dataAttr}
                            data-quill
                            disabled={!!disabledReason}
                            title={disabledReason}
                            className={cn(fullWidth ? 'w-full justify-start' : 'justify-start', className)}
                        >
                            <IconCalendar />
                            {label}
                        </Button>
                    }
                />
                <PopoverContent align="start" className="w-auto p-0">
                    <QuillDatePicker
                        value={value ? value.toDate() : new Date()}
                        maxDate={maxDate?.toDate()}
                        showTime={includeTime}
                        showTimeToggle={!!showTimeToggle}
                        onIncludeTimeChange={handleIncludeTimeChange}
                        onApply={applyDate}
                        onCancel={() => setOpen(false)}
                    />
                </PopoverContent>
            </Popover>
            {clearable && value && !disabledReason && (
                <Button
                    variant="outline"
                    aria-label="Clear date"
                    data-attr={dataAttr ? `${dataAttr}-clear` : undefined}
                    onClick={() => onChange(null)}
                >
                    <IconX />
                </Button>
            )}
        </div>
    )
}

function DatePickerLemon({
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
    size,
    type,
    className,
    disabledReason,
    visible,
    onOpen,
    onClickOutside,
    onClose,
    'data-attr': dataAttr,
}: DatePickerProps): JSX.Element {
    const buttonProps: NonNullable<LemonCalendarSelectInputProps['buttonProps']> = {
        fullWidth,
        size,
        type,
        className,
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
