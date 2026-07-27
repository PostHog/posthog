import clsx from 'clsx'
import { useRef, useState } from 'react'

import { IconX } from '@posthog/icons'

import { dayjs, dayjsNowInTimezone } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton, LemonButtonWithSideActionProps, SideAction } from 'lib/lemon-ui/LemonButton'
import {
    GetTimeStateOpts,
    LemonCalendar,
    LemonCalendarProps,
    timeDataAttr,
} from 'lib/lemon-ui/LemonCalendar/LemonCalendar'

import { LemonSwitch } from '../LemonSwitch'
import { Popover } from '../Popover'

export function getTimeElement(parent: HTMLElement | null, props: GetTimeStateOpts): HTMLDivElement | undefined | null {
    return parent?.querySelector(`[data-attr="${timeDataAttr(props)}"]`)
}
function scrollToTimeElement(calendarEl: HTMLDivElement | null, props: GetTimeStateOpts, skipAnimation: boolean): void {
    getTimeElement(calendarEl, props)?.scrollIntoView({
        block: 'start',
        inline: 'nearest',
        behavior: skipAnimation ? ('instant' as ScrollBehavior) : 'smooth',
    })
}

function proposedDate(
    target: dayjs.Dayjs | null,
    { value, unit }: GetTimeStateOpts,
    use24HourFormat: boolean = false
): dayjs.Dayjs {
    let date = target || dayjs().startOf('day')
    if (value != date.format(unit)) {
        if (unit === 'h') {
            if (use24HourFormat) {
                date = date.hour(Number(value))
            } else {
                date = date.hour(date.format('a') === 'am' || value === 12 ? Number(value) : Number(value) + 12)
            }
        } else if (unit === 'm') {
            date = date.minute(Number(value))
        } else if (unit === 'a') {
            date = value === 'am' ? date.subtract(12, 'hour') : date.add(12, 'hour')
        }
    }
    return date
}

function cloneTimeToDate(targetDate: dayjs.Dayjs, timeSource: dayjs.Dayjs): dayjs.Dayjs {
    return targetDate.clone().hour(timeSource.hour()).minute(timeSource.minute())
}

function getDateDisabledReason(
    selectionPeriod: 'past' | 'upcoming',
    date: dayjs.Dayjs,
    today: dayjs.Dayjs
): string | undefined {
    if (!selectionPeriod) {
        return undefined
    }

    // select future dates
    if (selectionPeriod === 'upcoming' && date.isBefore(today)) {
        return 'Cannot select dates in the past'
    }

    if (selectionPeriod === 'past' && date.isAfter(today)) {
        return 'Cannot select dates in the future'
    }

    return undefined
}

export interface LemonCalendarSelectProps {
    value?: dayjs.Dayjs | null
    onChange?: (date: dayjs.Dayjs) => void
    months?: number
    onClose?: () => void
    granularity?: LemonCalendarProps['granularity']
    selectionPeriod?: 'past' | 'upcoming'
    /** Timezone used to determine which past/future dates are selectable (defaults to browser local). */
    selectionPeriodTimezone?: string
    showTimeToggle?: boolean
    onToggleTime?: (value: boolean) => void
    /** Use 24-hour format instead of 12-hour with AM/PM */
    use24HourFormat?: boolean
}

export function LemonCalendarSelect({
    value,
    onChange,
    months,
    onClose,
    granularity = 'day',
    selectionPeriod,
    selectionPeriodTimezone,
    showTimeToggle,
    onToggleTime,
    use24HourFormat = false,
}: LemonCalendarSelectProps): JSX.Element {
    const calendarRef = useRef<HTMLDivElement | null>(null)
    const [selectValue, setSelectValue] = useState<dayjs.Dayjs | null>(value ? value.startOf(granularity) : null)

    // Evaluate "now" as the timezone's wall clock (naive local Dayjs) so it's comparable to picked dates.
    const now = selectionPeriodTimezone ? dayjsNowInTimezone(selectionPeriodTimezone) : dayjs()
    const today = now.startOf('day')

    const scrollToTime = (date: dayjs.Dayjs, skipAnimation: boolean): void => {
        const calendarEl = calendarRef.current
        if (calendarEl && date) {
            const hour = use24HourFormat ? date.hour() : date.hour() % 12 || 12
            scrollToTimeElement(calendarEl, { unit: 'h', value: hour }, skipAnimation)
            scrollToTimeElement(calendarEl, { unit: 'm', value: date.minute() }, skipAnimation)
        }
    }

    const onDateClick = (date: dayjs.Dayjs | null): void => {
        if (date) {
            date =
                granularity === 'minute'
                    ? date.minute(selectValue === null ? now.minute() : selectValue.minute())
                    : date.startOf('minute')

            date = ['hour', 'minute'].includes(granularity)
                ? date.hour(selectValue === null ? now.hour() : selectValue.hour())
                : date.startOf('hour')

            scrollToTime(date, true)
        }

        setSelectValue(date)
    }

    useOnMountEffect(() => {
        if (selectValue) {
            scrollToTime(selectValue, true)
        }
    })

    const onTimeClick = (props: GetTimeStateOpts): void => {
        const date = proposedDate(selectValue, props, use24HourFormat)
        scrollToTime(date, false)
        setSelectValue(date)
    }

    return (
        <div className="LemonCalendarSelect" data-attr="lemon-calendar-select">
            <div className="flex justify-between border-b p-2 pb-4">
                <h3 className="text-base mb-0">Select a date</h3>
                {onClose && (
                    <LemonButton icon={<IconX />} size="small" onClick={onClose} aria-label="close" noPadding />
                )}
            </div>
            <LemonCalendar
                ref={calendarRef}
                onDateClick={onDateClick}
                leftmostMonth={selectValue?.startOf('month')}
                months={months}
                getDateState={({ date }) => {
                    let disabledReason: string | undefined

                    if (selectionPeriod) {
                        disabledReason = getDateDisabledReason(selectionPeriod, date, today)

                        if (selectValue && date.isSame(today, 'date')) {
                            const selectedTimeOnDate = cloneTimeToDate(date, selectValue)

                            if (selectionPeriod === 'upcoming' && selectedTimeOnDate.isBefore(now)) {
                                disabledReason = 'Pick a time in the future first'
                            } else if (selectionPeriod === 'past' && selectedTimeOnDate.isAfter(now)) {
                                disabledReason = 'Pick a time in the past first'
                            }
                        }
                    }

                    return { disabledReason, selected: date.isSame(selectValue, 'd') }
                }}
                getTimeState={(props) => {
                    const selected = selectValue
                        ? props.unit === 'h' && use24HourFormat
                            ? String(selectValue.hour())
                            : selectValue.format(props.unit)
                        : null
                    const newDate = proposedDate(selectValue, props, use24HourFormat)

                    const periodValidityDisabledReason =
                        selectionPeriod === 'upcoming' && newDate.isBefore(now)
                            ? 'Cannot choose a time in the past'
                            : selectionPeriod === 'past' && newDate.isAfter(now)
                              ? 'Cannot choose a time in the future'
                              : undefined
                    const disabledReason = selectValue ? periodValidityDisabledReason : 'Choose a date first'

                    return {
                        active: selected === String(props.value),
                        disabledReason,
                        onClick: () => {
                            if (selected != props.value) {
                                onTimeClick(props)
                            }
                        },
                    }
                }}
                granularity={granularity}
                use24HourFormat={use24HourFormat}
            />
            <div
                className={clsx(
                    'flex deprecated-space-x-2 items-center border-t p-2 pt-4',
                    showTimeToggle ? 'justify-between' : 'justify-end'
                )}
            >
                {showTimeToggle && (
                    <LemonSwitch
                        label="Include time?"
                        checked={granularity != 'day'}
                        onChange={onToggleTime}
                        bordered
                    />
                )}
                <div className="flex deprecated-space-x-2">
                    {onClose && (
                        <LemonButton type="secondary" onClick={onClose} data-attr="lemon-calendar-select-cancel">
                            Cancel
                        </LemonButton>
                    )}
                    <LemonButton
                        type="primary"
                        disabled={!selectValue}
                        onClick={() => selectValue && onChange && onChange(selectValue)}
                        data-attr="lemon-calendar-select-apply"
                    >
                        Apply
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

export type LemonCalendarSelectInputProps = LemonCalendarSelectProps & {
    onChange?: (date: dayjs.Dayjs | null) => void
    onClickOutside?: () => void
    buttonProps?: Omit<LemonButtonWithSideActionProps, 'sideAction'> & { sideAction?: SideAction }
    placeholder?: string
    clearable?: boolean
    visible?: boolean
    format?: string
}

export function LemonCalendarSelectInput(props: LemonCalendarSelectInputProps): JSX.Element {
    const { buttonProps, placeholder, clearable, visible: controlledVisible, ...calendarProps } = props
    const [uncontrolledVisible, setUncontrolledVisible] = useState(false)

    const visible = controlledVisible ?? uncontrolledVisible

    const showClear = props.value && clearable

    return (
        <Popover
            actionable
            onClickOutside={() => {
                setUncontrolledVisible(false)
                props.onClickOutside?.()
            }}
            visible={visible}
            overlay={
                <LemonCalendarSelect
                    {...calendarProps}
                    onChange={(value) => {
                        props.onChange?.(value)
                        setUncontrolledVisible(false)
                    }}
                    onClose={() => {
                        setUncontrolledVisible(false)
                        props.onClose?.()
                    }}
                />
            }
        >
            <LemonButton
                onClick={() => setUncontrolledVisible(true)}
                type="secondary"
                fullWidth
                sideAction={
                    showClear
                        ? {
                              icon: <IconX />,
                              onClick: () => props.onChange?.(null),
                              'aria-label': 'Clear date',
                          }
                        : (undefined as unknown as SideAction) // We know it will be a normal button if not clearable
                }
                {...props.buttonProps}
            >
                {props.value?.format(
                    props.format ??
                        `MMMM D, YYYY${
                            props.granularity === 'minute'
                                ? props.use24HourFormat
                                    ? ' HH:mm'
                                    : ' h:mm A'
                                : props.granularity === 'hour'
                                  ? props.use24HourFormat
                                      ? ' HH:00'
                                      : ' h A'
                                  : ''
                        }`
                ) ??
                    placeholder ??
                    'Select date'}
            </LemonButton>
        </Popover>
    )
}
