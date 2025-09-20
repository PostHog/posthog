import clsx from 'clsx'
import { useMemo, useRef, useState } from 'react'

import { IconX } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton, LemonButtonProps, LemonButtonWithSideActionProps, SideAction } from 'lib/lemon-ui/LemonButton'
import {
    GetLemonButtonTimePropsOpts,
    LemonCalendar,
    LemonCalendarProps,
} from 'lib/lemon-ui/LemonCalendar/LemonCalendar'

import { LemonSwitch } from '../LemonSwitch'
import { Popover } from '../Popover'

function timeDataAttr({ unit, value }: GetLemonButtonTimePropsOpts): string {
    return `${value}-${unit}`
}

export function getTimeElement(
    parent: HTMLElement | null,
    props: GetLemonButtonTimePropsOpts
): HTMLDivElement | undefined | null {
    return parent?.querySelector(`[data-attr="${timeDataAttr(props)}"]`)
}
function scrollToTimeElement(
    calendarEl: HTMLDivElement | null,
    props: GetLemonButtonTimePropsOpts,
    skipAnimation: boolean
): void {
    getTimeElement(calendarEl, props)?.scrollIntoView({
        block: 'start',
        inline: 'nearest',
        behavior: skipAnimation ? ('instant' as ScrollBehavior) : 'smooth',
    })
}

function proposedDate(target: dayjs.Dayjs | null, { value, unit }: GetLemonButtonTimePropsOpts): dayjs.Dayjs {
    let date = target || dayjs().startOf('day')
    if (value != date.format(unit)) {
        if (unit === 'h') {
            date = date.hour(date.format('a') === 'am' || value === 12 ? Number(value) : Number(value) + 12)
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
    today: dayjs.Dayjs,
    selectionPeriodLimit?: dayjs.Dayjs | null
): string | undefined {
    if (!selectionPeriod) {
        return undefined
    }

    // select future dates
    if (selectionPeriod === 'upcoming' && date.isBefore(today)) {
        return 'Cannot select dates in the past'
    }

    // select future dates after a limit
    if (selectionPeriod === 'upcoming' && selectionPeriodLimit && date.isAfter(selectionPeriodLimit, 'day')) {
        return 'Cannot select dates after the limit'
    }

    if (selectionPeriod === 'past' && date.isAfter(today)) {
        return 'Cannot select dates in the future'
    }

    // select past dates before a limit
    if (selectionPeriod === 'past' && selectionPeriodLimit && date.isBefore(selectionPeriodLimit, 'day')) {
        return 'Cannot select dates before the limit'
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
    selectionPeriodLimit?: dayjs.Dayjs | null
    showTimeToggle?: boolean
    onToggleTime?: (value: boolean) => void
}

export function LemonCalendarSelect({
    value,
    onChange,
    months,
    onClose,
    granularity = 'day',
    selectionPeriod,
    selectionPeriodLimit,
    showTimeToggle,
    onToggleTime,
}: LemonCalendarSelectProps): JSX.Element {
    const calendarRef = useRef<HTMLDivElement | null>(null)
    const [selectValue, setSelectValue] = useState<dayjs.Dayjs | null>(value ? value.startOf(granularity) : null)

    const now = dayjs()
    const today = now.startOf('day')
    const isAM = useMemo(() => selectValue?.format('a') === 'am', [selectValue])

    const scrollToTime = (date: dayjs.Dayjs, skipAnimation: boolean): void => {
        const calendarEl = calendarRef.current
        if (calendarEl && date) {
            const hour = isAM ? date.hour() : date.hour() - 12
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

    const onTimeClick = (props: GetLemonButtonTimePropsOpts): void => {
        const date = proposedDate(selectValue, props)
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
                getLemonButtonProps={({ date, props }) => {
                    const modifiedProps: LemonButtonProps = { ...props }

                    if (selectionPeriod) {
                        const isToday = date.isSame(today, 'date')

                        modifiedProps.disabledReason = getDateDisabledReason(
                            selectionPeriod,
                            date,
                            today,
                            selectionPeriodLimit
                        )

                        // select date disabled reason
                        if (selectValue && isToday) {
                            // select time disabled reason
                            const selectedTimeOnDate = cloneTimeToDate(date, selectValue)

                            if (selectionPeriod === 'upcoming' && selectedTimeOnDate.isBefore(now)) {
                                modifiedProps.disabledReason = 'Pick a time in the future first'
                            } else if (selectionPeriod === 'past' && selectedTimeOnDate.isAfter(now)) {
                                modifiedProps.disabledReason = 'Pick a time in the past first'
                            }
                        }
                    }

                    if (date.isSame(selectValue, 'd')) {
                        return { ...modifiedProps, status: 'default', type: 'primary' }
                    }
                    return modifiedProps
                }}
                getLemonButtonTimeProps={(props) => {
                    const selected = selectValue ? selectValue.format(props.unit) : null
                    const newDate = proposedDate(selectValue, props)

                    const periodValidityDisabledReason =
                        selectionPeriod === 'upcoming' && newDate.isBefore(now)
                            ? 'Cannot choose a time in the past'
                            : selectionPeriod === 'past' && newDate.isAfter(now)
                              ? 'Cannot choose a time in the future'
                              : undefined
                    const disabledReason = selectValue ? periodValidityDisabledReason : 'Choose a date first'

                    return {
                        active: selected === String(props.value),
                        className: 'rounded-none',
                        'data-attr': timeDataAttr(props),
                        disabledReason: disabledReason,
                        onClick: () => {
                            if (selected != props.value) {
                                onTimeClick(props)
                            }
                        },
                    }
                }}
                granularity={granularity}
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
                          }
                        : (undefined as unknown as SideAction) // We know it will be a normal button if not clearable
                }
                {...props.buttonProps}
            >
                {props.value?.format(
                    props.format ??
                        `MMMM D, YYYY${
                            props.granularity === 'minute' ? ' h:mm A' : props.granularity === 'hour' ? ' h A' : ''
                        }`
                ) ??
                    placeholder ??
                    'Select date'}
            </LemonButton>
        </Popover>
    )
}
