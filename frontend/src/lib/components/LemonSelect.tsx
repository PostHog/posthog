import { LemonDivider } from '@posthog/lemon-ui'
import React, { useEffect, useMemo, useState } from 'react'
import { IconClose } from './icons'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithPopupProps } from './LemonButton'
import { PopupProps } from './Popup/Popup'

export interface LemonSelectOption {
    label: string | JSX.Element
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
    className?: string
    popup?: {
        className?: string
        ref?: React.MutableRefObject<HTMLDivElement | null>
    }
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
    className,
    popup,
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
                className={className}
                popup={{
                    ref: popup?.ref,
                    overlay: sections.map((section, i) => (
                        <React.Fragment key={i}>
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
                                    type="stealth"
                                    /* Intentionally == instead of === because JS treats object number keys as strings, */
                                    /* messing comparisons up a bit */
                                    active={key == localValue}
                                    disabled={option.disabled}
                                    fullWidth
                                    data-attr={option['data-attr']}
                                >
                                    {option.label || key}
                                    {option.element}
                                </LemonButton>
                            ))}
                            {i < sections.length - 1 ? <LemonDivider /> : null}
                        </React.Fragment>
                    )),
                    sameWidth: dropdownMatchSelectWidth,
                    placement: dropdownPlacement,
                    actionable: true,
                    className: popup?.className,
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
                    icon={<IconClose className="text-base" />}
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
