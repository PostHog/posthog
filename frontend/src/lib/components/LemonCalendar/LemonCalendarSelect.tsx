import { LemonCalendar, LemonCalendarProps } from 'lib/components/LemonCalendar/LemonCalendar'
import React, { useState } from 'react'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/components/LemonButton'
import { IconClose } from 'lib/components/icons'

export interface LemonCalendarSelectProps {
    value?: string | null
    onChange: (date: string) => void
    months?: number
    getLemonButtonProps?: LemonCalendarProps['getLemonButtonProps']
    onClose?: () => void
}

export function LemonCalendarSelect({ value, onChange, months, onClose }: LemonCalendarSelectProps): JSX.Element {
    const parsedValue = value ? dayjs(value).format('YYYY-MM-DD') : undefined
    const [selectValue, setSelectValue] = useState(parsedValue)

    return (
        <div className="LemonCalendarSelect">
            <div className="flex justify-between border-b p-2 pb-4">
                <h3 className="mb-0">Select a date</h3>
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
                    onClick={setSelectValue}
                    firstMonth={selectValue}
                    months={months}
                    getLemonButtonProps={(date, _, defaultProps) => {
                        if (date === selectValue) {
                            return { ...defaultProps, status: 'primary', type: 'primary' }
                        }
                        return defaultProps
                    }}
                />
            </div>
            <div className="flex space-x-2 justify-end items-center border-t p-2 pt-4">
                <LemonButton type="secondary" onClick={onClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    disabled={!selectValue}
                    onClick={() => selectValue && onChange(selectValue)}
                >
                    Apply
                </LemonButton>
            </div>
        </div>
    )
}
