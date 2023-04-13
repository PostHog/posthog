import React, { useEffect, useMemo, useState } from 'react'
import { IconClose } from '../icons'
import { LemonButton, LemonButtonWithDropdownProps } from '../LemonButton'
import { PopoverProps } from '../Popover'
import './LemonSelect.scss'
import clsx from 'clsx'
import { TooltipProps } from '../Tooltip'
import {
    LemonMenu,
    LemonMenuItem,
    LemonMenuItemBase,
    LemonMenuItemLeaf,
    LemonMenuItemNode,
    LemonMenuItems,
    LemonMenuSection,
} from '../LemonMenu/LemonMenu'

type LemonSelectOptionBase = Omit<LemonMenuItemBase, 'active' | 'status'> // Select handles active state internally

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

type OnChange<T> = (newValue: T | null) => void
type OnSelect<T> = (newValue: T) => void
export interface LemonSelectProps<T>
    extends Pick<
        LemonButtonWithDropdownProps,
        'id' | 'className' | 'loading' | 'fullWidth' | 'disabled' | 'data-attr' | 'aria-label' | 'onClick' | 'tabIndex'
    > {
    options: LemonSelectOptions<T>
    /** Null only is valid for clearable selects. */
    value?: T | null
    /** Callback fired when a value different from the one currently set is selected. */
    onChange?: OnChange<T>
    /** Callback fired when a value is selected, even if it already is set. */
    onSelect?: OnSelect<T>
    optionTooltipPlacement?: TooltipProps['placement']
    dropdownMatchSelectWidth?: boolean
    dropdownMaxContentWidth?: boolean
    dropdownPlacement?: PopoverProps['placement']
    allowClear?: boolean
    className?: string
    placeholder?: string
    size?: 'small' | undefined
    popover?: {
        className?: string
        ref?: React.MutableRefObject<HTMLDivElement | null>
    }
}

export function LemonSelect<T>({
    value = null,
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
    popover,
    ...buttonProps
}: LemonSelectProps<T>): JSX.Element {
    const [activeValue, setActiveValue] = useState<T | null>(value)

    useEffect(() => {
        if (!buttonProps.loading) {
            setActiveValue(value)
        }
    }, [value, buttonProps.loading])

    const wrappedOnSelect: OnSelect<T> = (newValue) => {
        if (newValue !== activeValue) {
            onChange?.(newValue)
            setActiveValue(newValue)
        }
        onSelect?.(newValue)
    }

    const [items, allLeafOptions] = useMemo(
        () => convertSelectOptionsToMenuItems(options, activeValue, wrappedOnSelect),
        [options, activeValue]
    )

    const isClearButtonShown = allowClear && !!activeValue

    return (
        <LemonMenu
            items={items}
            tooltipPlacement={optionTooltipPlacement}
            sameWidth={dropdownMatchSelectWidth}
            placement={dropdownPlacement}
            actionable
            className={popover?.className}
            maxContentWidth={dropdownMaxContentWidth}
        >
            <LemonButton
                className={clsx(className, isClearButtonShown && 'LemonSelect--clearable')}
                icon={allLeafOptions.find((o) => o.value === activeValue)?.icon}
                // so that the pop-up isn't shown along with the close button
                sideIcon={isClearButtonShown ? <div /> : undefined}
                type="secondary"
                status="stealth"
                {...buttonProps}
            >
                <span>
                    {allLeafOptions.find((o) => o.value === activeValue)?.label ?? activeValue ?? (
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
                            setActiveValue(null)
                        }}
                    />
                )}
            </LemonButton>
        </LemonMenu>
    )
}

/**
 * The select can receive `options` that are either Options or Sections.
 *
 * To simplify the implementation we box the options so that the code only deals with sections
 * and also generate a single list of options since selection is separate from display structure
 * */
function convertSelectOptionsToMenuItems<T>(
    options: LemonSelectOptions<T>,
    activeValue: T | null,
    onSelect: OnSelect<T>
): [LemonMenuItems, LemonSelectOptionLeaf<T>[]] {
    const leafOptionsAccumulator: LemonSelectOptionLeaf<T>[] = []
    const items: LemonMenuItems = options.map((option) =>
        convertToMenuSingle(option, activeValue, onSelect, leafOptionsAccumulator)
    )
    return [items, leafOptionsAccumulator]
}

function convertToMenuSingle<T>(
    option: LemonSelectOption<T> | LemonSelectSection<T>,
    activeValue: T | null,
    onSelect: OnSelect<T>,
    acc: LemonSelectOptionLeaf<T>[]
): LemonMenuItem | LemonMenuSection {
    if (isLemonSelectSection(option)) {
        const { options: childOptions, ...section } = option
        return {
            ...section,
            items: option.options.map((o) => convertToMenuSingle(o, activeValue, onSelect, acc)),
        } as LemonMenuSection
    } else if (isLemonSelectOptionNode(option)) {
        const { options: childOptions, ...node } = option
        return {
            ...node,
            active: doOptionsContainActiveValue(childOptions, activeValue),
            items: childOptions.map((o) => convertToMenuSingle(o, activeValue, onSelect, acc)),
        } as LemonMenuItemNode
    } else {
        acc.push(option)
        const { value, ...leaf } = option
        return {
            ...leaf,
            active: value === activeValue,
            onClick: () => onSelect(value),
        } as LemonMenuItemLeaf
    }
}

export function isLemonSelectSection<T>(
    candidate: LemonSelectSection<T> | LemonSelectOption<T>
): candidate is LemonSelectSection<T> {
    return candidate && 'options' in candidate && !('label' in candidate)
}

export function isLemonSelectOptionNode<T>(
    candidate: LemonSelectSection<T> | LemonSelectOption<T>
): candidate is LemonSelectOptionNode<T> {
    return candidate && 'options' in candidate && 'label' in candidate
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
