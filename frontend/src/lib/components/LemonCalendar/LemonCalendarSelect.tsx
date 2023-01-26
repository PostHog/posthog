import { LemonCalendar } from 'lib/components/LemonCalendar/LemonCalendar'
import { useState } from 'react'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/components/LemonButton'
import { IconClose } from 'lib/components/icons'

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
                    <LemonButton
                        icon={<IconClose />}
                        size="small"
                        status="stealth"
                        onClick={onClose}
                        aria-label="close"
                    />
                )}
            </div>
            <div className="p-2">
                <LemonCalendar
                    onDateClick={setSelectValue}
                    leftmostMonth={selectValue?.startOf('month')}
                    months={months}
                    getLemonButtonProps={({ date, props }) => {
                        if (date.isSame(selectValue, 'd')) {
                            return { ...props, status: 'primary', type: 'primary' }
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
