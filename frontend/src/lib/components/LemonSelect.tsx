import { LemonDivider } from '@posthog/lemon-ui'
import React, { useEffect, useMemo, useState } from 'react'
import { IconClose } from './icons'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithPopupProps } from './LemonButton'
import { PopupProps } from './Popup/Popup'
import './LemonSelect.scss'
import clsx from 'clsx'

export interface LemonSelectOption<T> {
    value: T
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

const isSection = <T extends any>(
    candidate: LemonSelectSection<T> | LemonSelectOption<T>
): candidate is LemonSelectSection<T> => candidate && 'options' in candidate

/**
 * The select can receive options that are a mix of Options and Sections.
 *
 * To simplify the implementation we box the options so that the code only deals with sections
 * and generate a single list of options since selection is separate from display structure
 * */
const boxToSections = <T,>(
    sectionsAndOptions: LemonSelectSection<T>[] | LemonSelectOption<T>[]
): [LemonSelectSection<T>[], LemonSelectOption<T>[]] => {
    let allOptions: LemonSelectOption<T>[] = []
    const sections: LemonSelectSection<T>[] = []
    let implicitSection: LemonSelectSection<T> = { options: [] }
    for (const sectionOrOption of sectionsAndOptions) {
        if (isSection(sectionOrOption)) {
            if (implicitSection.options.length > 0) {
                sections.push(implicitSection)
                implicitSection = { options: [] }
            }
            sections.push(sectionOrOption)
            allOptions = allOptions.concat(sectionOrOption.options)
        } else {
            allOptions.push(sectionOrOption)
            implicitSection.options.push(sectionOrOption)
        }
    }
    if (implicitSection.options.length > 0) {
        sections.push(implicitSection)
    }

    return [sections, allOptions]
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

    const [sections, allOptions] = useMemo(() => boxToSections(options), [options])

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
                                        if (option.value != localValue) {
                                            onChange?.(option.value)
                                            setLocalValue(option.value)
                                        }
                                    }}
                                    status="stealth"
                                    /* Intentionally == instead of === because JS treats object number keys as strings, */
                                    /* messing comparisons up a bit */
                                    active={option.value == localValue}
                                    disabled={option.disabled}
                                    fullWidth
                                    data-attr={option['data-attr']}
                                >
                                    {option.label || option.value}
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
                icon={localValue && allOptions.find((o) => o.value == localValue)?.icon}
                // so that the pop-up isn't shown along with the close button
                sideIcon={isClearButtonShown ? <div /> : undefined}
                type="secondary"
                status="stealth"
                {...buttonProps}
            >
                <span>
                    {(localValue && (allOptions.find((o) => o.value == localValue)?.label || localValue)) || (
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
