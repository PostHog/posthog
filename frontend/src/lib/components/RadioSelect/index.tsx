import React from 'react'
import './index.scss'

export interface RadioSelectType {
    key: string
    label: string
    icon?: React.ReactNode
}

interface RadioSelectProps {
    options: RadioSelectType[]
    selectedOption: null | string | string[]
    onOptionChanged: (key: string | string[] | null) => void
    multipleSelection?: boolean
}

export function RadioSelect({
    options,
    selectedOption,
    onOptionChanged,
    multipleSelection,
}: RadioSelectProps): JSX.Element {
    const isSelected = (option: RadioSelectType): boolean => {
        return multipleSelection && selectedOption
            ? selectedOption?.includes(option.key)
            : selectedOption === option.key
    }

    const handleClick = (option: RadioSelectType): void => {
        if (multipleSelection) {
            if (selectedOption instanceof Array) {
                const _selectedOptions = selectedOption
                const idx = _selectedOptions.indexOf(option.key)
                if (idx > -1) {
                    // Option was previously selected, remove
                    _selectedOptions.splice(idx, 1)
                } else {
                    _selectedOptions.push(option.key)
                }
                onOptionChanged(_selectedOptions)
            } else {
                onOptionChanged([option.key])
            }
        } else {
            onOptionChanged(selectedOption !== option.key ? option.key : null)
        }
    }

    return (
        <div className="ph-radio-options">
            {options.map((option) => (
                <div
                    className={`radio-option${isSelected(option) ? ' active' : ''}`}
                    key={option.key}
                    onClick={() => handleClick(option)}
                >
                    <div className="graphic">{option.icon}</div>
                    <div className="label">{option.label}</div>
                </div>
            ))}
        </div>
    )
}
