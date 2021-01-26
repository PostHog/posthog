import React from 'react'
import './index.scss'

export interface RadioSelectType {
    key: string
    label: string
    icon?: React.ReactNode
}

interface RadioSelectProps {
    options: RadioSelectType[]
    selectedOption: null | string
    onOptionChanged: (key: string | null) => void
}

export function RadioSelect({ options, selectedOption, onOptionChanged }: RadioSelectProps): JSX.Element {
    return (
        <div className="ph-radio-options">
            {options.map((option) => (
                <div
                    className={`radio-option${selectedOption === option.key ? ' active' : ''}`}
                    key={option.key}
                    onClick={() => onOptionChanged(selectedOption !== option.key ? option.key : null)}
                >
                    <div className="graphic">{option.icon}</div>
                    <div className="label">{option.label}</div>
                </div>
            ))}
        </div>
    )
}
