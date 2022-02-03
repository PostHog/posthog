import React, { useState } from 'react'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithPopupProps } from './LemonButton'

export interface LemonSelectOption {
    label?: string
    icon?: React.ReactElement
}

export type LemonSelectOptions = Record<string | number, LemonSelectOption>

export interface LemonSelectProps<O extends LemonSelectOptions>
    extends Omit<LemonButtonWithPopupProps, 'popup' | 'icon' | 'value' | 'onChange'> {
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

    return (
        <LemonButtonWithPopup
            popup={{
                overlay: Object.entries(options).map(([key, option]) => (
                    <LemonButton
                        key={key}
                        icon={option.icon}
                        onClick={() => {
                            onChange(key)
                            setLocalValue(key)
                        }}
                        type={
                            /* Intentionally == instead of === because JS treats object number keys as strings, */
                            /* messing comparisons up a bit */
                            key == localValue ? 'highlighted' : 'stealth'
                        }
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
