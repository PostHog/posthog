import React from 'react'
import { ArrowLeftOutlined } from '@ant-design/icons'
import './index.scss'
import { Button } from 'antd'

export interface RadioSelectType {
    key: string
    label: string
    icon?: React.ReactNode
}

interface RadioSelectProps {
    options: RadioSelectType[]
    selectedOption: null | string | string[]
    onOptionChanged: (key: string | string[] | null) => void
    identifier: string // main identifier for the component (to support autocapture)
    multipleSelection?: boolean
    focusSelection?: boolean // will hide other choices after making a selection
}

export function RadioSelect({
    options,
    selectedOption,
    onOptionChanged,
    identifier,
    multipleSelection,
    focusSelection,
}: RadioSelectProps): JSX.Element {
    const isSelected = (option: RadioSelectType): boolean => {
        return multipleSelection && selectedOption
            ? selectedOption?.includes(option.key)
            : selectedOption === option.key
    }

    const handleClick = (option: RadioSelectType | null): void => {
        if (!option) {
            onOptionChanged(null)
            return
        }

        if (multipleSelection) {
            if (selectedOption instanceof Array) {
                const _selectedOptions = [...selectedOption]
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
        <div className="mt-4">
            {focusSelection && selectedOption && (
                <div className="text-center">
                    <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => handleClick(null)}>
                        change
                    </Button>
                </div>
            )}
            <div className="ph-radio-options">
                {options.map((option) => {
                    if (!focusSelection || !selectedOption || isSelected(option)) {
                        return (
                            <div
                                className={`radio-option${isSelected(option) ? ' active' : ''}`}
                                key={option.key}
                                onClick={() => handleClick(option)}
                                data-attr={`radio-select-${identifier}`}
                                data-detail={`radio-select-${identifier}-${option.key}`}
                            >
                                <div className="graphic">{option.icon}</div>
                                <div className="label">{option.label}</div>
                            </div>
                        )
                    }
                })}
            </div>
        </div>
    )
}
