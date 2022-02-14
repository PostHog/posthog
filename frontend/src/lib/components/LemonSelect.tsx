import React, { useEffect, useState } from 'react'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithPopupProps } from './LemonButton'

export interface LemonSelectOption {
    label?: string
    icon?: React.ReactElement
    disabled?: boolean
}

export type LemonSelectOptions = Record<string | number, LemonSelectOption>

export interface LemonSelectProps<O extends LemonSelectOptions>
    extends Omit<LemonButtonWithPopupProps, 'popup' | 'icon' | 'value' | 'defaultValue' | 'onChange'> {
    options: O
    value: keyof O
    onChange: (newValue: keyof O) => void
    dropdownMatchSelectWidth?: boolean
}

export function LemonSelect<O extends LemonSelectOptions>({
    value,
    onChange,
    options,
    dropdownMatchSelectWidth = true,
    ...buttonProps
}: LemonSelectProps<O>): JSX.Element {
    const [localValue, setLocalValue] = useState(value)

    useEffect(() => {
        if (!buttonProps.loading) {
            setLocalValue(value)
        }
    }, [value, buttonProps.loading])

    return (
        <LemonButtonWithPopup
            popup={{
                overlay: Object.entries(options).map(([key, option]) => (
                    <LemonButton
                        key={key}
                        icon={option.icon}
                        onClick={() => {
                            if (key != localValue) {
                                onChange(key)
                                setLocalValue(key)
                            }
                        }}
                        type={
                            /* Intentionally == instead of === because JS treats object number keys as strings, */
                            /* messing comparisons up a bit */
                            key == localValue ? 'highlighted' : 'stealth'
                        }
                        disabled={option.disabled}
                        fullWidth
                    >
                        {option.label || key}
                    </LemonButton>
                )),
                sameWidth: dropdownMatchSelectWidth,
                actionable: true,
            }}
            icon={options[localValue]?.icon}
            {...buttonProps}
        >
            {options[localValue]?.label || localValue}
        </LemonButtonWithPopup>
    )
}
