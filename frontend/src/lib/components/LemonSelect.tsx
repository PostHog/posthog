import { LemonDivider } from '@posthog/lemon-ui'
import React, { useEffect, useMemo, useState } from 'react'
import { IconClose } from './icons'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithPopupProps } from './LemonButton'
import { PopupProps } from './Popup/Popup'
import './LemonSelect.scss'
import clsx from 'clsx'

export interface LemonSelectOption<T> {
    key: T
    label: string | JSX.Element
    icon?: React.ReactElement
    disabled?: boolean
    'data-attr'?: string
    element?: React.ReactElement
}

export type LemonSelectOptions<T> = LemonSelectSection<T>[] | LemonSelectOption<T>[]

export interface LemonSelectSection<T> {
    title?: string | React.ReactNode
    options: LemonSelectOption<T>[]
}

export interface LemonSelectProps<T>
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
    options: LemonSelectOptions<T>
    value?: T
    onChange?: (newValue: T | null) => void
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

function isSections<T>(candidate: LemonSelectOptions<T>): candidate is LemonSelectSection<T>[] {
    return candidate.length > 0 && 'options' in candidate[0]
}

export function LemonSelect<T>({
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
}: LemonSelectProps<T>): JSX.Element {
    const [localValue, setLocalValue] = useState(value)

    const isClearButtonShown = allowClear && !!localValue

    useEffect(() => {
        if (!buttonProps.loading) {
            setLocalValue(value)
        }
    }, [value, buttonProps.loading])

    const [sections, allOptions] = useMemo(() => {
        let sections: LemonSelectSection<T>[]
        if (isSections(options)) {
            sections = options
        } else {
            sections = [{ options }]
        }

        const allOptions = sections.flatMap((section) => section.options)

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
                            {section.title ? (
                                typeof section.title === 'string' ? (
                                    <h5>{section.title}</h5>
                                ) : (
                                    section.title
                                )
                            ) : null}
                            {section.options.map((option, index) => (
                                <LemonButton
                                    key={index}
                                    icon={option.icon}
                                    onClick={() => {
                                        if (option.key != localValue) {
                                            onChange?.(option.key)
                                            setLocalValue(option.key)
                                        }
                                    }}
                                    status="stealth"
                                    /* Intentionally == instead of === because JS treats object number keys as strings, */
                                    /* messing comparisons up a bit */
                                    active={option.key == localValue}
                                    disabled={option.disabled}
                                    fullWidth
                                    data-attr={option['data-attr']}
                                >
                                    {option.label || option.key}
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
                icon={localValue && allOptions.find((o) => o.key == localValue)?.icon}
                // so that the pop-up isn't shown along with the close button
                sideIcon={isClearButtonShown ? <div /> : undefined}
                type="secondary"
                status="stealth"
                {...buttonProps}
            >
                <span>
                    {(localValue && (allOptions.find((o) => o.key == localValue)?.label || localValue)) || (
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
                            setLocalValue(undefined)
                        }}
                    />
                )}
            </LemonButtonWithPopup>
        </div>
    )
}
