import { LemonDivider } from '@posthog/lemon-ui'
import React, { useEffect, useMemo, useState } from 'react'
import { IconClose } from './icons'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithPopupProps } from './LemonButton'
import { PopupProps } from './Popup/Popup'
import './LemonSelect.scss'
import clsx from 'clsx'

export interface LemonSelectOption {
    label: string | JSX.Element
    icon?: React.ReactElement
    disabled?: boolean
    'data-attr'?: string
    element?: React.ReactElement
}

export type LemonSelectOptions = Record<string | number, LemonSelectOption>

export interface LemonSelectSection {
    label?: string | React.ReactNode
    options: LemonSelectOptions
}
// export type LemonSelectSections = Record<string, LemonSelectSection>

export interface LemonSelectProps
    extends Pick<
        LemonButtonWithPopupProps,
        | 'id'
        | 'className'
        | 'icon'
        | 'sideIcon'
        | 'loading'
        | 'tooltip'
        | 'fullWidth'
        | 'disabled'
        | 'noPadding'
        | 'data-attr'
        | 'data-tooltip'
        | 'aria-label'
        | 'onClick'
        | 'tabIndex'
    > {
    options: LemonSelectOptions | LemonSelectSection[]
    value?: keyof LemonSelectOptions | null
    onChange?: (newValue: keyof LemonSelectOptions | null) => void
    dropdownMatchSelectWidth?: boolean
    dropdownMaxContentWidth?: boolean
    dropdownPlacement?: PopupProps['placement']
    allowClear?: boolean
    className?: string
    placeholder?: string
    size?: 'small' | undefined
    popup?: {
        className?: string
        ref?: React.MutableRefObject<HTMLDivElement | null>
    }
}

export function LemonSelect({
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
}: LemonSelectProps): JSX.Element {
    const [localValue, setLocalValue] = useState(value)

    const isClearButtonShown = allowClear && !!localValue

    useEffect(() => {
        if (!buttonProps.loading) {
            setLocalValue(value)
        }
    }, [value, buttonProps.loading])

    const [sections, allOptions] = useMemo(() => {
        const sections: LemonSelectSection[] = Array.isArray(options)
            ? options
            : [
                  {
                      label: '',
                      options: options,
                  } as LemonSelectSection,
              ]

        const allOptions = Object.values(sections).reduce(
            (acc, x) => ({
                ...acc,
                ...x.options,
            }),
            {} as LemonSelectOptions
        )

        return [sections, allOptions]
    }, [options])

    return (
        <div className="flex">
            <LemonButtonWithPopup
                className={clsx(className, isClearButtonShown && 'LemonSelect--clearable')}
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
                                    status="stealth"
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
                icon={localValue ? allOptions[localValue]?.icon : undefined}
                // so that the pop-up isn't shown along with the close button
                sideIcon={isClearButtonShown ? <div /> : undefined}
                type="secondary"
                status="stealth"
                {...buttonProps}
            >
                <span>
                    {(localValue && (allOptions[localValue]?.label || localValue)) || (
                        <span className="text-muted">{placeholder}</span>
                    )}
                </span>
                {isClearButtonShown && (
                    <LemonButton
                        className="LemonSelect--button--clearable"
                        type="tertiary"
                        status="stealth"
                        noPadding
                        icon={<IconClose />}
                        tooltip="Clear selection"
                        onClick={() => {
                            onChange?.(null)
                            setLocalValue(null)
                        }}
                    />
                )}
            </LemonButtonWithPopup>
        </div>
    )
}
