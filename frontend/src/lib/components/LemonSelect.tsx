import { LemonDivider } from '@posthog/lemon-ui'
import React, { useEffect, useMemo, useState } from 'react'
import { IconClose } from './icons'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithPopupProps } from './LemonButton'
import { PopupProps } from './Popup/Popup'

export interface LemonSelectOption {
    label: string
    icon?: React.ReactElement
    disabled?: boolean
    'data-attr'?: string
    element?: React.ReactElement
}

export type LemonSelectOptions = Record<string | number, LemonSelectOption>

export interface LemonSelectSection<O> {
    label?: string | React.ReactNode
    options: O
}

export type LemonSelectSections<LemonSelectOptions> = Record<string, LemonSelectSection<LemonSelectOptions>>

export interface LemonSelectProps<O extends LemonSelectOptions>
    extends Omit<LemonButtonWithPopupProps, 'popup' | 'icon' | 'value' | 'defaultValue' | 'onChange'> {
    options: O | LemonSelectSection<O>[]
    value?: keyof O | null
    onChange?: (newValue: keyof O | null) => void
    dropdownMatchSelectWidth?: boolean
    dropdownMaxContentWidth?: boolean
    dropdownPlacement?: PopupProps['placement']
    allowClear?: boolean
}

export function LemonSelect<O extends LemonSelectOptions>({
    value,
    onChange,
    options,
    placeholder = 'Select a value',
    dropdownMatchSelectWidth = true,
    dropdownMaxContentWidth = false,
    dropdownPlacement,
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

    const [sections, allOptions] = useMemo(() => {
        const sections: LemonSelectSection<O>[] = Array.isArray(options)
            ? options
            : [
                  {
                      label: '',
                      options: options,
                  },
              ]

        const allOptions = Object.values(sections).reduce(
            (acc, x) => ({
                ...acc,
                ...x.options,
            }),
            {} as O
        )

        return [sections, allOptions]
    }, [options])

    return (
        <div
            className="LemonButtonWithSideAction"
            onMouseEnter={() => setHover(true)}
            onMouseLeave={() => setHover(false)}
        >
            <LemonButtonWithPopup
                popup={{
                    overlay: sections.map((section, i) => (
                        <>
                            {section.label ? (
                                typeof section.label === 'string' ? (
                                    <h5>{section.label}</h5>
                                ) : (
                                    section.label
                                )
                            ) : null}
                            {Object.entries(section.options).map(([key, option]) => (
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
                            ))}
                            {i < sections.length - 1 ? <LemonDivider /> : null}
                        </>
                    )),
                    sameWidth: dropdownMatchSelectWidth,
                    placement: dropdownPlacement,
                    actionable: true,
                    maxContentWidth: dropdownMaxContentWidth,
                }}
                icon={localValue && allOptions[localValue]?.icon}
                sideIcon={isClearButtonShown ? <div /> : undefined}
                {...buttonProps}
            >
                {(localValue && (allOptions[localValue]?.label || localValue)) || (
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
