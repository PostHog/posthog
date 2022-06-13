import React, { useEffect, useState } from 'react'
import { IconClose } from './icons'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithPopupProps } from './LemonButton'

export interface LemonSelectOption {
    label: string
    icon?: React.ReactElement
    disabled?: boolean
    'data-attr'?: string
    element?: React.ReactElement
}

export type LemonSelectOptions = Record<string | number, LemonSelectOption>

export interface LemonSelectProps<O extends LemonSelectOptions>
    extends Omit<LemonButtonWithPopupProps, 'popup' | 'icon' | 'value' | 'defaultValue' | 'onChange'> {
    options: O
    value?: keyof O | null
    onChange?: (newValue: keyof O | null) => void
    dropdownMatchSelectWidth?: boolean
    allowClear?: boolean
}

export function LemonSelect<O extends LemonSelectOptions>({
    value,
    onChange,
    options,
    placeholder = 'Select a value',
    dropdownMatchSelectWidth = true,
    allowClear = false,
    ...buttonProps
}: LemonSelectProps<O>): JSX.Element {
    const [localValue, setLocalValue] = useState(value)
    const [hover, setHover] = useState(false)

    const isClearButtonShown = allowClear && hover && !!localValue

    useEffect(() => {
        if (!buttonProps.loading) {
            setLocalValue(value)
        }
    }, [value, buttonProps.loading])

    return (
        <div
            className="LemonButtonWithSideAction"
            onMouseEnter={() => setHover(true)}
            onMouseLeave={() => setHover(false)}
        >
            <LemonButtonWithPopup
                popup={{
                    overlay: Object.entries(options).map(([key, option]) => (
                        <LemonButton
                            key={key}
                            icon={option.icon}
                            onClick={() => {
                                if (key != localValue) {
                                    onChange?.(key)
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
                            data-attr={option['data-attr']}
                        >
                            {option.label || key}
                            {option.element}
                        </LemonButton>
                    )),
                    sameWidth: dropdownMatchSelectWidth,
                    actionable: true,
                }}
                icon={localValue && options[localValue]?.icon}
                sideIcon={isClearButtonShown ? <div /> : undefined}
                {...buttonProps}
            >
                {(localValue && (options[localValue]?.label || localValue)) || (
                    <span className="text-muted">{placeholder}</span>
                )}
            </LemonButtonWithPopup>
            {isClearButtonShown && (
                <LemonButton
                    className="LemonButtonWithSideAction--side-button"
                    type="tertiary"
                    icon={<IconClose style={{ fontSize: '1rem' }} />}
                    tooltip="Clear selection"
                    onClick={() => {
                        onChange?.(null)
                        setLocalValue(null)
                    }}
                />
            )}
        </div>
    )
}
