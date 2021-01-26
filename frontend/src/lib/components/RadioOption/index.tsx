import React from 'react'
import './index.scss'

export interface RadioOption {
    key: string | number
    label: string
    icon?: any // any, because Ant Design icons are some weird ForwardRefExoticComponent type
}

interface RadioOptionProps {
    options: RadioOption[]
    selectedOption?: null | string
    onOptionChanged: (key: string | number) => void
}

export function RadioOption({ options, selectedOption, onOptionChanged }: RadioOptionProps): JSX.Element {
    return (
        <div className="ph-radio-options">
            {options.map((option) => (
                <div
                    className={`radio-option${selectedOption === option.key ? ' active' : ''}`}
                    key={option.key}
                    onClick={() => onOptionChanged(option.key)}
                >
                    <div className="graphic">{option.icon}</div>
                    <div className="label">{option.label}</div>
                </div>
            ))}
        </div>
    )
}
