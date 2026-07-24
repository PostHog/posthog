import { useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar, IconX } from '@posthog/icons'
import {
    Button,
    cn,
    DatePicker as QuillDatePicker,
    type Day,
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '@posthog/quill'

import { dayjs, dayjsNowInTimezone } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonCalendarSelectInput, LemonCalendarSelectInputProps } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { teamLogic } from 'scenes/teamLogic'

/**
 * Design-system-agnostic single-date picker — the migration seam between the LemonUI
 * calendar family and Quill's DatePicker. Callers depend on this dayjs-facing API;
 * the internal rendering swaps from LemonUI to Quill in one place without touching callers.
 *
 * The swap is gated by the `QUILL_DATE_PICKER` feature flag so LemonUI and Quill run side
 * by side and roll back without a revert. The Quill panel covers the full prop surface:
 * day/minute granularity, 12/24-hour time entry, selection windows (rendered as datetime
 * bounds computed here, in the selection timezone), and controlled visibility. The LemonUI
 * renderer remains only as the flag-off path until the flag is removed.
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
    granularity?: 'day' | 'minute'
    /** Restrict selectable dates relative to now. */
    selectionPeriod?: 'past' | 'upcoming'
    /** Timezone used to decide which past/upcoming dates are selectable (defaults to browser local). */
    selectionPeriodTimezone?: string
    /** Offer an "Include time?" toggle that flips granularity between day and minute. */
    showTimeToggle?: boolean
    onToggleTime?: (includeTime: boolean) => void
    /** Use 24-hour time entry instead of 12-hour with AM/PM. */
    use24HourFormat?: boolean
    /** Latest selectable date. When omitted the picker is unbounded above. */
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
    /** Trigger button style. Mapped to the underlying button per backing renderer (secondary -> Quill outline; primary -> Quill primary; tertiary -> Quill default). When unset, the Quill trigger uses its neutral `outline`. */
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
const QUILL_TRIGGER_DATETIME_FORMAT_24H = 'MMMM D, YYYY HH:mm'
const QUILL_TRIGGER_DATETIME_FORMAT_12H = 'MMMM D, YYYY h:mm A'

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

export function DatePicker(props: DatePickerProps): JSX.Element {
    const quillEnabled = useFeatureFlag('QUILL_DATE_PICKER')
    if (quillEnabled) {
        return <DatePickerQuill {...props} />
    }
    return <DatePickerLemon {...props} />
}

function DatePickerQuill({
    value,
    onChange,
    granularity,
    selectionPeriod,
    selectionPeriodTimezone,
    showTimeToggle,
    onToggleTime,
    use24HourFormat,
    placeholder,
    clearable,
    format,
    fullWidth = true,
    size = 'medium',
    type = 'secondary',
    className,
    disabledReason,
    maxDate,
    visible,
    onOpen,
    onClickOutside,
    onClose,
    'data-attr': dataAttr,
}: DatePickerProps): JSX.Element {
    const { weekStartDay } = useValues(teamLogic)
    const [uncontrolledOpen, setUncontrolledOpen] = useState(false)
    const [includeTime, setIncludeTime] = useState(granularity === 'minute')

    const open = visible ?? uncontrolledOpen
    const labelFormat =
        format ??
        (includeTime
            ? use24HourFormat
                ? QUILL_TRIGGER_DATETIME_FORMAT_24H
                : QUILL_TRIGGER_DATETIME_FORMAT_12H
            : QUILL_TRIGGER_FORMAT)
    const label = value ? value.format(labelFormat) : (placeholder ?? 'Select date')

    // Quill has no relative selection-window concept, only absolute bounds — so evaluate "now"
    // here (as the selection timezone's wall clock, comparable to the panel's naive dates) and
    // hand the panel the resulting min/max. The panel's calendar disables by day and clamps
    // applied datetimes, matching the LemonUI behavior of blocking wrong-direction times.
    const selectionNow = selectionPeriod
        ? selectionPeriodTimezone
            ? dayjsNowInTimezone(selectionPeriodTimezone)
            : dayjs()
        : null
    const panelMinDate = selectionPeriod === 'upcoming' && selectionNow ? selectionNow.toDate() : undefined
    const panelMaxDate =
        selectionPeriod === 'past' && selectionNow
            ? (maxDate && maxDate.isBefore(selectionNow) ? maxDate : selectionNow).toDate()
            : maxDate?.toDate()

    const handleOpenChange = (nextOpen: boolean): void => {
        if (nextOpen) {
            onOpen?.()
        } else {
            onClickOutside?.()
        }
        setUncontrolledOpen(nextOpen)
    }

    const handleIncludeTimeChange = (next: boolean): void => {
        setIncludeTime(next)
        onToggleTime?.(next)
    }

    const applyDate = (next: Date): void => {
        onChange(dayjs(next))
        setUncontrolledOpen(false)
    }

    return (
        <div className={fullWidth ? 'flex w-full items-center gap-1' : 'flex items-center gap-1'}>
            <Popover open={open} onOpenChange={handleOpenChange}>
                <PopoverTrigger
                    render={
                        <Button
                            variant={QUILL_TRIGGER_VARIANT[type]}
                            size={QUILL_TRIGGER_SIZE[size]}
                            data-attr={dataAttr}
                            data-quill
                            disabled={!!disabledReason}
                            title={disabledReason}
                            className={cn('justify-start', fullWidth && 'w-full', className)}
                        >
                            <IconCalendar />
                            {label}
                        </Button>
                    }
                />
                <PopoverContent align="start" className="w-auto p-0">
                    <QuillDatePicker
                        value={value ? value.toDate() : new Date()}
                        minDate={panelMinDate}
                        maxDate={panelMaxDate}
                        weekStartsOn={weekStartDay as Day}
                        hourCycle={use24HourFormat ? 24 : 12}
                        showTime={includeTime}
                        showTimeToggle={!!showTimeToggle}
                        onIncludeTimeChange={handleIncludeTimeChange}
                        onApply={applyDate}
                        onCancel={() => {
                            onClose?.()
                            setUncontrolledOpen(false)
                        }}
                    />
                </PopoverContent>
            </Popover>
            {clearable && value && !disabledReason && (
                <Button
                    variant="outline"
                    size={QUILL_TRIGGER_SIZE[size]}
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
        className,
        disabledReason,
        'data-attr': dataAttr,
    }
    // Only forward `type` when the caller set one — LemonCalendarSelectInput defaults the trigger to
    // `secondary` and spreads `buttonProps` after it, so a `type: undefined` here would clobber that default.
    if (type) {
        buttonProps.type = type
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
