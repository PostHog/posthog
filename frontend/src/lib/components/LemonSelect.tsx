import { LemonDivider } from '@posthog/lemon-ui'
import { useEffect, useMemo, useState } from 'react'
import { IconClose } from './icons'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithPopupProps } from './LemonButton'
import { PopupProps } from './Popup/Popup'
import './LemonSelect.scss'
import clsx from 'clsx'
import { TooltipProps } from './Tooltip'

export interface LemonSelectOption<T> {
    value: T
    label: string | JSX.Element
    icon?: React.ReactElement
    sideIcon?: React.ReactElement
    disabled?: boolean
    tooltip?: string | JSX.Element
    'data-attr'?: string
    element?: React.ReactElement // TODO: Unify with `label`
}

export type LemonSelectOptions<T> = LemonSelectSection<T>[] | LemonSelectOption<T>[]

export interface LemonSelectSection<T> {
    title?: string | React.ReactNode
    options: LemonSelectOption<T>[]
    footer?: string | React.ReactNode
}

export interface LemonSelectProps<T>
    extends Pick<
        LemonButtonWithPopupProps,
        'id' | 'className' | 'loading' | 'fullWidth' | 'disabled' | 'data-attr' | 'aria-label' | 'onClick' | 'tabIndex'
    > {
    options: LemonSelectOptions<T>
    value?: T
    /** Callback fired when a value different from the one currently set is selected. */
    onChange?: (newValue: T | null) => void
    /** Callback fired when a value is selected, even if it already is set. */
    onSelect?: (newValue: T) => void
    optionTooltipPlacement?: TooltipProps['placement']
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

export const isLemonSelectSection = <T extends any>(
    candidate: LemonSelectSection<T> | LemonSelectOption<T>
): candidate is LemonSelectSection<T> => candidate && 'options' in candidate

/**
 * The select can receive `options` that are either Options or Sections.
 *
 * To simplify the implementation we box the options so that the code only deals with sections
 * and also generate a single list of options since selection is separate from display structure
 * */
export const boxToSections = <T,>(
    sectionsAndOptions: LemonSelectSection<T>[] | LemonSelectOption<T>[]
): [LemonSelectSection<T>[], LemonSelectOption<T>[]] => {
    let allOptions: LemonSelectOption<T>[] = []
    const sections: LemonSelectSection<T>[] = []
    let implicitSection: LemonSelectSection<T> = { options: [] }
    for (const sectionOrOption of sectionsAndOptions) {
        if (isLemonSelectSection(sectionOrOption)) {
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
    onSelect,
    options,
    placeholder = 'Select a value',
    optionTooltipPlacement,
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
                        <div key={i} className="space-y-px">
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
                                    sideIcon={option.sideIcon}
                                    tooltip={option.tooltip}
                                    tooltipPlacement={optionTooltipPlacement}
                                    onClick={() => {
                                        if (option.value !== localValue) {
                                            onChange?.(option.value)
                                            setLocalValue(option.value)
                                        }
                                        onSelect?.(option.value)
                                    }}
                                    status="stealth"
                                    active={option.value === localValue}
                                    disabled={option.disabled}
                                    fullWidth
                                    data-attr={option['data-attr']}
                                >
                                    {option.label ?? option.value}
                                    {option.element}
                                </LemonButton>
                            ))}
                            {section.footer ? <div>{section.footer}</div> : null}
                            {i < sections.length - 1 ? <LemonDivider /> : null}
                        </div>
                    )),
                    sameWidth: dropdownMatchSelectWidth,
                    placement: dropdownPlacement,
                    actionable: true,
                    className: popup?.className,
                    maxContentWidth: dropdownMaxContentWidth,
                }}
                icon={allOptions.find((o) => o.value === localValue)?.icon}
                // so that the pop-up isn't shown along with the close button
                sideIcon={isClearButtonShown ? <div /> : undefined}
                type="secondary"
                status="stealth"
                {...buttonProps}
            >
                <span>
                    {allOptions.find((o) => o.value === localValue)?.label ?? localValue ?? (
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
