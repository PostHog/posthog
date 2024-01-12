import { dayjs } from 'lib/dayjs'
import { IconClose } from 'lib/lemon-ui/icons'
import { LemonButton, LemonButtonWithSideActionProps, SideAction } from 'lib/lemon-ui/LemonButton'
import { LemonCalendar } from 'lib/lemon-ui/LemonCalendar/LemonCalendar'
import { useState } from 'react'

import { Popover } from '../Popover'

export interface LemonCalendarSelectProps {
    value?: dayjs.Dayjs | null
    onChange: (date: dayjs.Dayjs) => void
    months?: number
    onClose?: () => void
}

export function LemonCalendarSelect({ value, onChange, months, onClose }: LemonCalendarSelectProps): JSX.Element {
    const [selectValue, setSelectValue] = useState<dayjs.Dayjs | null>(value ? value.startOf('day') : null)

    return (
        <div className="LemonCalendarSelect" data-attr="lemon-calendar-select">
            <div className="flex justify-between border-b p-2 pb-4">
                <h3 className="text-base mb-0">Select a date</h3>
                {onClose && (
                    <LemonButton icon={<IconClose />} size="small" onClick={onClose} aria-label="close" noPadding />
                )}
            </div>
            <div className="p-2">
                <LemonCalendar
                    onDateClick={setSelectValue}
                    leftmostMonth={selectValue?.startOf('month')}
                    months={months}
                    getLemonButtonProps={({ date, props }) => {
                        if (date.isSame(selectValue, 'd')) {
                            return { ...props, status: 'default', type: 'primary' }
                        }
                        return props
                    }}
                />
            </div>
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
                              icon: <IconClose />,
                              onClick: () => props.onChange(null),
                          }
                        : (undefined as unknown as SideAction) // We know it will be a normal button if not clearable
                }
                {...props.buttonProps}
            >
                {props.value?.format('MMMM D, YYYY') ?? placeholder ?? 'Select date'}
            </LemonButton>
        </Popover>
    )
}
