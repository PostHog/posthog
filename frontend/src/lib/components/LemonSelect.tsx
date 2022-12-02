import { LemonDivider } from '@posthog/lemon-ui'
import { useEffect, useMemo, useState } from 'react'
import { IconClose } from './icons'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithPopupProps } from './LemonButton'
import { PopupProps } from './Popup/Popup'
import './LemonSelect.scss'
import clsx from 'clsx'
import { TooltipProps } from './Tooltip'
import { TooltipPlacement } from 'antd/lib/tooltip'

interface LemonSelectOptionBase {
    label: string | JSX.Element
    icon?: React.ReactElement
    sideIcon?: React.ReactElement
    /** Like plain `disabled`, except we enforce a reason to be shown in the tooltip. */
    disabledReason?: string
    tooltip?: string | JSX.Element
    'data-attr'?: string
}

export interface LemonSelectOptionLeaf<T> extends LemonSelectOptionBase {
    value: T
    element?: React.ReactElement
}

export interface LemonSelectOptionNode<T> extends LemonSelectOptionBase {
    options: LemonSelectOption<T>[]
}

export type LemonSelectOption<T> = LemonSelectOptionLeaf<T> | LemonSelectOptionNode<T>

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
): candidate is LemonSelectSection<T> => candidate && 'options' in candidate && !('label' in candidate)

function extractLeafOptions<T>(targetArray: LemonSelectOptionLeaf<T>[], options: LemonSelectOption<T>[]): void {
    for (const option of options) {
        if ('options' in option) {
            extractLeafOptions(targetArray, option.options)
        } else {
            targetArray.push(option)
        }
    }
}

/**
 * The select can receive `options` that are either Options or Sections.
 *
 * To simplify the implementation we box the options so that the code only deals with sections
 * and also generate a single list of options since selection is separate from display structure
 * */
export const boxToSections = <T,>(
    sectionsAndOptions: LemonSelectSection<T>[] | LemonSelectOption<T>[]
): [LemonSelectSection<T>[], LemonSelectOptionLeaf<T>[]] => {
    const allOptions: LemonSelectOptionLeaf<T>[] = []
    const sections: LemonSelectSection<T>[] = []
    let implicitSection: LemonSelectSection<T> = { options: [] }
    for (const sectionOrOption of sectionsAndOptions) {
        if (isLemonSelectSection(sectionOrOption)) {
            if (implicitSection.options.length > 0) {
                sections.push(implicitSection)
                implicitSection = { options: [] }
            }
            sections.push(sectionOrOption)
            extractLeafOptions(allOptions, sectionOrOption.options)
        } else {
            extractLeafOptions(allOptions, [sectionOrOption])
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

    const [sections, allLeafOptions] = useMemo(() => boxToSections(options), [options])

    return (
        <div className="flex">
            <LemonButtonWithPopup
                className={clsx(className, isClearButtonShown && 'LemonSelect--clearable')}
                popup={{
                    ref: popup?.ref,
                    overlay: sections.map((section, i) => (
                        <>
                            <div key={i} className="space-y-px">
                                {section.title ? (
                                    typeof section.title === 'string' ? (
                                        <h5>{section.title}</h5>
                                    ) : (
                                        section.title
                                    )
                                ) : null}
                                {section.options.map((option, index) => (
                                    <LemonSelectOptionRow
                                        key={index}
                                        option={option}
                                        onSelect={(newValue) => {
                                            if (newValue !== localValue) {
                                                onChange?.(newValue)
                                                setLocalValue(newValue)
                                            }
                                            onSelect?.(newValue)
                                        }}
                                        activeValue={localValue}
                                        tooltipPlacement={optionTooltipPlacement}
                                    />
                                ))}
                                {section.footer ? <div>{section.footer}</div> : null}
                            </div>
                            {i < sections.length - 1 ? <LemonDivider /> : null}
                        </>
                    )),
                    sameWidth: dropdownMatchSelectWidth,
                    placement: dropdownPlacement,
                    actionable: true,
                    className: popup?.className,
                    maxContentWidth: dropdownMaxContentWidth,
                }}
                icon={allLeafOptions.find((o) => o.value === localValue)?.icon}
                // so that the pop-up isn't shown along with the close button
                sideIcon={isClearButtonShown ? <div /> : undefined}
                type="secondary"
                status="stealth"
                {...buttonProps}
            >
                <span>
                    {allLeafOptions.find((o) => o.value === localValue)?.label ?? localValue ?? (
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

function doOptionsContainActiveValue<T>(options: LemonSelectOption<T>[], activeValue: T | null): boolean {
    for (const option of options) {
        if ('options' in option) {
            if (doOptionsContainActiveValue(option.options, activeValue)) {
                return true
            }
        } else if (option.value === activeValue) {
            return true
        }
    }
    return false
}

function LemonSelectOptionRow<T>({
    option,
    activeValue,
    onSelect,
    tooltipPlacement,
}: {
    option: LemonSelectOption<T>
    activeValue: T | undefined
    onSelect: (value: T) => void
    tooltipPlacement: TooltipPlacement | undefined
}): JSX.Element {
    const disabled = !!option.disabledReason

    let tooltipContent: string | JSX.Element | undefined
    if (option.tooltip && option.disabledReason) {
        // TODO: Pull this logic into LemonButton, so that `disabledReason` is a thing in the entire design system
        tooltipContent = (
            <>
                {option.tooltip}
                <div className="mt-1 italic">{option.disabledReason}</div>
            </>
        )
    } else {
        tooltipContent = option.disabledReason ? (
            <span className="italic">{option.disabledReason}</span>
        ) : (
            option.tooltip
        )
    }

    return 'options' in option ? (
        <LemonButtonWithPopup
            icon={option.icon}
            sideIcon={option.sideIcon}
            tooltip={tooltipContent}
            tooltipPlacement={tooltipPlacement}
            status="stealth"
            disabled={disabled}
            fullWidth
            data-attr={option['data-attr']}
            active={doOptionsContainActiveValue(option.options, activeValue)}
            popup={{
                overlay: (
                    <div className="space-y-px">
                        {option.options.map((option, index) => (
                            <LemonSelectOptionRow
                                key={index}
                                option={option}
                                onSelect={onSelect}
                                activeValue={activeValue}
                                tooltipPlacement={tooltipPlacement}
                            />
                        ))}
                    </div>
                ),
                placement: 'right-start',
                actionable: true,
                closeParentPopupOnClickInside: true,
            }}
        >
            {option.label}
        </LemonButtonWithPopup>
    ) : (
        <LemonButton
            icon={option.icon}
            sideIcon={option.sideIcon}
            tooltip={tooltipContent}
            tooltipPlacement={tooltipPlacement}
            status="stealth"
            disabled={disabled}
            fullWidth
            data-attr={option['data-attr']}
            active={option.value === activeValue}
            onClick={() => onSelect(option.value)}
        >
            {option.label ?? option.value}
            {option.element}
        </LemonButton>
    )
}
