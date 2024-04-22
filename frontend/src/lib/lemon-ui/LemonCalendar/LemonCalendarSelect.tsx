import { IconX } from '@posthog/icons'
import { dayjs } from 'lib/dayjs'
import { LemonButton, LemonButtonWithSideActionProps, SideAction } from 'lib/lemon-ui/LemonButton'
import { GetLemonButtonTimePropsOpts, LemonCalendar } from 'lib/lemon-ui/LemonCalendar/LemonCalendar'
import { useEffect, useMemo, useRef, useState } from 'react'

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

export interface LemonCalendarSelectProps {
    value?: dayjs.Dayjs | null
    onChange: (date: dayjs.Dayjs) => void
    months?: number
    onClose?: () => void
    showTime?: boolean
    fromToday?: boolean
}

export function LemonCalendarSelect({
    value,
    onChange,
    months,
    onClose,
    showTime,
    fromToday,
}: LemonCalendarSelectProps): JSX.Element {
    const calendarRef = useRef<HTMLDivElement | null>(null)
    const [selectValue, setSelectValue] = useState<dayjs.Dayjs | null>(
        value ? (showTime ? value : value.startOf('day')) : null
    )

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
        const now = dayjs()

        if (date) {
            date = showTime ? date.hour(selectValue === null ? now.hour() : selectValue.hour()) : date.startOf('hour')
            date = showTime
                ? date.minute(selectValue === null ? now.minute() : selectValue.minute())
                : date.startOf('minute')
            scrollToTime(date, true)
        }

        setSelectValue(date)
    }

    useEffect(() => {
        if (selectValue) {
            scrollToTime(selectValue, true)
        }
    }, [])

    const onTimeClick = (props: GetLemonButtonTimePropsOpts): void => {
        const { value, unit } = props

        let date = selectValue || dayjs().startOf('day')
        if (unit === 'h') {
            date = date.hour(date.format('a') === 'am' ? Number(value) : Number(value) + 12)
        } else if (unit === 'm') {
            date = date.minute(Number(value))
        } else if (unit === 'a') {
            date = value === 'am' ? date.subtract(12, 'hour') : date.add(12, 'hour')
        }

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
                    if (date.isSame(selectValue, 'd')) {
                        return { ...props, status: 'default', type: 'primary' }
                    }
                    return props
                }}
                getLemonButtonTimeProps={(props) => {
                    const selected = selectValue ? selectValue.format(props.unit) : null
                    return {
                        active: selected === String(props.value),
                        className: 'rounded-none',
                        'data-attr': timeDataAttr(props),
                        onClick: () => {
                            if (selected != props.value) {
                                onTimeClick(props)
                            }
                        },
                    }
                }}
                showTime={showTime}
                fromToday={fromToday}
            />
            <div className="flex space-x-2 justify-end items-center border-t p-2 pt-4">
                <LemonButton type="secondary" onClick={onClose} data-attr="lemon-calendar-select-cancel">
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    disabled={!selectValue}
                    onClick={() => selectValue && onChange(selectValue)}
                    data-attr="lemon-calendar-select-apply"
                >
                    Apply
                </LemonButton>
            </div>
        </div>
    )
}

export function LemonCalendarSelectInput(
    props: LemonCalendarSelectProps & {
        onChange: (date: dayjs.Dayjs | null) => void
        buttonProps?: LemonButtonWithSideActionProps
        placeholder?: string
        clearable?: boolean
    }
): JSX.Element {
    const { buttonProps, placeholder, clearable, ...calendarProps } = props
    const [visible, setVisible] = useState(false)

    const showClear = props.value && clearable

    return (
        <Popover
            actionable
            onClickOutside={() => setVisible(false)}
            visible={visible}
            overlay={
                <LemonCalendarSelect
                    {...calendarProps}
                    onChange={(value) => {
                        props.onChange(value)
                        setVisible(false)
                    }}
                    onClose={() => {
                        setVisible(false)
                        props.onClose?.()
                    }}
                />
            }
        >
            <LemonButton
                onClick={() => setVisible(true)}
                type="secondary"
                fullWidth
                sideAction={
                    showClear
                        ? {
                              icon: <IconX />,
                              onClick: () => props.onChange(null),
                          }
                        : (undefined as unknown as SideAction) // We know it will be a normal button if not clearable
                }
                {...props.buttonProps}
            >
                {props.value?.format(`MMMM D, YYYY${props.showTime && ' h:mm A'}`) ?? placeholder ?? 'Select date'}
            </LemonButton>
        </Popover>
    )
}
