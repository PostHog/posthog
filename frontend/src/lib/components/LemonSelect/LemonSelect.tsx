import React, { useEffect, useMemo, useState } from 'react'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithPopupProps } from 'lib/components/LemonButton'
import clsx from 'clsx'
import { PopupProps } from 'lib/components/Popup/Popup'
import { LemonSpacer } from 'lib/components/LemonRow'
import { IconClose } from 'lib/components/icons'

export interface LemonSelectOptionData {
    className?: string
    label: string | React.ReactNode | ((option: Record<string, any>) => React.ReactNode)
    icon?: React.ReactElement
    disabled?: boolean
    'data-attr'?: string
}

export type LemonSelectOptions<O extends LemonSelectOptionData> = Record<string | number, O>
export type LemonSelectGroupOrFlatOptions<O extends LemonSelectOptionData> = Record<
    string | number,
    LemonSelectOptions<O> | O
>
export type LemonSelectPopup = Omit<PopupProps, 'children' | 'overlay'>

function isGroupOption<O extends LemonSelectOptionData>(
    option: LemonSelectOptions<O> | O
): option is LemonSelectOptions<O> {
    return (option as O)?.label === undefined
}
function isFlatOption<O extends LemonSelectOptionData>(option: LemonSelectOptions<O> | O): option is O {
    return (option as O)?.label !== undefined
}

function computeLabel(
    label: string | React.ReactNode | ((option: Record<string, any>) => React.ReactNode),
    option: LemonSelectOptionData
): React.ReactNode {
    return typeof label === 'function' ? label(option) : label
}

export interface LemonSelectProps<O extends LemonSelectOptionData>
    extends Omit<LemonButtonWithPopupProps, 'popup' | 'icon' | 'value' | 'defaultValue' | 'onChange'> {
    /** Options can be either 1-level nested (grouped with key as label) or flat objects. */
    options: LemonSelectGroupOrFlatOptions<O>
    value: keyof LemonSelectOptions<O> | null
    onChange: (newValue: keyof LemonSelectOptions<O> | null) => void
    dropdownMatchSelectWidth?: boolean
    allowClear?: boolean
    /** Classname for control input label */
    controlClassName?: string
    /** Classname for dropdown menu */
    dropdownClassName?: string
    /** Popup props to extend on defaults */
    popup?: LemonSelectPopup
    /** Whether to show icons in dropdown menu. */
    showDropdownIcon?: boolean
}

interface LemonSelectOptionProps<Q extends LemonSelectOptionData> {
    optionKey: string
    currentKey: string | number | symbol | null
    option: Q
    onClick: (key: string) => void
    showDropdownIcon?: boolean
}

function LemonSelectOption<Q extends LemonSelectOptionData>({
    optionKey,
    currentKey,
    option,
    onClick,
    showDropdownIcon,
}: LemonSelectOptionProps<Q>): JSX.Element {
    const computedLabel = computeLabel(option.label, option) || optionKey

    return (
        <LemonButton
            className="LemonSelect__dropdown__option"
            key={optionKey}
            icon={showDropdownIcon ? option.icon : undefined}
            onClick={() => {
                if (optionKey != currentKey) {
                    onClick(optionKey)
                }
            }}
            type={
                /* Intentionally == instead of === because JS treats object number keys as strings, */
                /* messing comparisons up a bit */
                optionKey == currentKey ? 'highlighted' : 'stealth'
            }
            disabled={option.disabled}
            fullWidth
            data-attr={option['data-attr']}
        >
            {computedLabel}
        </LemonButton>
    )
}

export function LemonSelect<O extends LemonSelectOptionData>({
    className,
    controlClassName,
    dropdownClassName,
    value,
    onChange,
    options,
    placeholder,
    dropdownMatchSelectWidth = true,
    allowClear = false,
    showDropdownIcon = true,
    popup,
    ...buttonProps
}: LemonSelectProps<O>): JSX.Element {
    const flattenedOptions = useMemo(() => {
        return Object.entries(options).reduce<LemonSelectOptions<O>>((aggregation, [key, flatOrGroupOption]) => {
            if (isGroupOption(flatOrGroupOption)) {
                return { ...aggregation, ...flatOrGroupOption }
            }
            // Typescript isn't smart enough to determine that if option isn't a group option, it should be typed as a flat option
            if (isFlatOption(flatOrGroupOption)) {
                return { ...aggregation, [key]: flatOrGroupOption }
            }
            return aggregation
        }, {})
    }, [options])
    const [localValue, setLocalValue] = useState(value)
    const [hover, setHover] = useState(false)

    const isClearButtonShown = allowClear && hover && !!localValue

    useEffect(() => {
        if (!buttonProps.loading) {
            setLocalValue(value)
        }
    }, [value, buttonProps.loading])

    if (Object.keys(flattenedOptions).length < 1) {
        return <></>
    }

    return (
        <div
            className={clsx('LemonSelect', 'LemonButtonWithSideAction', className)}
            onMouseEnter={() => setHover(true)}
            onMouseLeave={() => setHover(false)}
        >
            <LemonButtonWithPopup
                popup={{
                    ...popup,
                    className: dropdownClassName,
                    overlay: Object.entries(options).map(([key, flatOrGroupOption]) => {
                        if (isGroupOption(flatOrGroupOption)) {
                            return (
                                <div className="LemonSelect__dropdown__grouped-options">
                                    <h5>{key}</h5>
                                    <LemonSpacer />
                                    {Object.entries(flatOrGroupOption).map(([optionKey, flatOption]) => (
                                        <LemonSelectOption
                                            key={`${key}-${optionKey}`}
                                            optionKey={optionKey}
                                            currentKey={localValue}
                                            option={flatOption}
                                            onClick={(_key) => {
                                                onChange(_key)
                                                setLocalValue(_key)
                                            }}
                                            showDropdownIcon={showDropdownIcon}
                                        />
                                    ))}
                                </div>
                            )
                        }

                        return (
                            <LemonSelectOption
                                key={key}
                                optionKey={key}
                                currentKey={localValue}
                                option={flatOrGroupOption}
                                onClick={(_key) => {
                                    onChange(_key)
                                    setLocalValue(_key)
                                }}
                                showDropdownIcon={showDropdownIcon}
                            />
                        )
                    }),
                    sameWidth: dropdownMatchSelectWidth,
                    actionable: true,
                }}
                icon={localValue ? flattenedOptions[localValue]?.icon : undefined}
                sideIcon={isClearButtonShown ? <div /> : undefined}
                {...buttonProps}
            >
                {(localValue && (
                    <span className={clsx('LemonSelect__control__label', controlClassName)}>
                        {computeLabel(flattenedOptions[localValue]?.label || '', flattenedOptions[localValue]) ||
                            localValue}
                    </span>
                )) || <span className="text-muted">{placeholder}</span>}
            </LemonButtonWithPopup>
            {isClearButtonShown && (
                <LemonButton
                    className="side-button"
                    type="tertiary"
                    icon={<IconClose />}
                    tooltip="Clear selection"
                    onClick={() => {
                        onChange(null)
                        setLocalValue(null)
                    }}
                />
            )}
        </div>
    )
}
