import clsx from 'clsx'
import React, { useMemo } from 'react'

import { IconX } from '@posthog/icons'

import { LemonDropdownProps } from 'lib/lemon-ui/LemonDropdown'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { LemonButton, LemonButtonProps } from '../LemonButton'
import {
    LemonMenu,
    LemonMenuItem,
    LemonMenuItemBase,
    LemonMenuItemLeaf,
    LemonMenuItemNode,
    LemonMenuProps,
    LemonMenuSection,
    isLemonMenuSection,
} from '../LemonMenu/LemonMenu'
import { PopoverProps } from '../Popover'
import { TooltipProps } from '../Tooltip'

// Select options are basically menu items that handle onClick and active state internally
interface LemonSelectOptionBase extends Omit<LemonMenuItemBase, 'active' | 'status'> {
    /** Support this option if it already is selected, but otherwise don't allow selecting it by hiding it. */
    hidden?: boolean
}

type LemonSelectCustomControl<T> = ({ onSelect }: { onSelect: (newValue: T) => void }) => JSX.Element
export interface LemonSelectOptionLeaf<T> extends LemonSelectOptionBase {
    value: T
    /**
     * Label for display inside the dropdown menu.
     *
     * If you really need something more advanced than a button, this also allows providing a custom control component,
     * which takes an `onSelect` prop. Can be for example a textarea with an "Apply value" button. Use this sparingly!
     */
    labelInMenu?: string | JSX.Element | LemonSelectCustomControl<T>
}

export interface LemonSelectOptionNode<T> extends LemonSelectOptionBase {
    options: LemonSelectOptions<T>
}

export type LemonSelectOption<T> = LemonSelectOptionLeaf<T> | LemonSelectOptionNode<T>

export interface LemonSelectSection<T> {
    title?: string | React.ReactNode
    options: LemonSelectOption<T>[]
    footer?: string | React.ReactNode
}

export type LemonSelectOptions<T> = LemonSelectSection<T>[] | LemonSelectOption<T>[]

export interface LemonSelectPropsBase<T>
    extends Pick<
        LemonButtonProps,
        | 'id'
        | 'className'
        | 'loading'
        | 'fullWidth'
        | 'disabled'
        | 'disabledReason'
        | 'data-attr'
        | 'aria-label'
        | 'onClick'
        | 'tabIndex'
        | 'type'
        | 'tooltip'
        | 'icon'
    > {
    options: LemonSelectOptions<T>
    /** Callback fired when a value is selected, even if it already is set. */
    onSelect?: (newValue: T) => void
    optionTooltipPlacement?: TooltipProps['placement']
    dropdownMatchSelectWidth?: boolean
    dropdownMaxContentWidth?: boolean
    dropdownPlacement?: PopoverProps['placement']
    className?: string
    placeholder?: string
    size?: LemonButtonProps['size']
    menu?: Pick<LemonMenuProps, 'className' | 'closeParentPopoverOnClickInside'>
    visible?: LemonDropdownProps['visible']
    startVisible?: LemonDropdownProps['startVisible']
    /** Access control props for automatic permission checking */
    accessControl?: {
        userLevel: AccessControlLevel
        minLevel: AccessControlLevel
        resource: AccessControlResourceType
    }
}

export interface LemonSelectPropsClearable<T> extends LemonSelectPropsBase<T> {
    allowClear: true
    /** Should only be undefined in form fields. */
    value?: T | null
    /** Callback fired when a value different from the one currently set is selected. */
    onChange?: (newValue: T | null) => void
    renderButtonContent?: (leaf: LemonSelectOptionLeaf<T | null> | undefined) => string | JSX.Element
}

export interface LemonSelectPropsNonClearable<T> extends LemonSelectPropsBase<T> {
    allowClear?: false
    /** Should only be undefined in form fields. */
    value?: T
    /** Callback fired when a value different from the one currently set is selected. */
    onChange?: (newValue: T) => void
    renderButtonContent?: (leaf: LemonSelectOptionLeaf<T | null> | undefined) => string | JSX.Element
}

export type LemonSelectProps<T> = LemonSelectPropsClearable<T> | LemonSelectPropsNonClearable<T>

export function LemonSelect<T extends string | number | boolean | null>({
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
    menu,
    renderButtonContent,
    visible,
    startVisible,
    accessControl,
    ...buttonProps
}: LemonSelectProps<T>): JSX.Element {
    const [items, allLeafOptions] = useMemo(
        () =>
            convertSelectOptionsToMenuItems(options, value, (newValue) => {
                if (newValue !== value) {
                    onChange?.(newValue)
                }
                onSelect?.(newValue)
            }),
        [options, value, onChange, onSelect]
    )

    const activeLeaf = allLeafOptions.find((o) => o.value === value)
    const isClearButtonShown = allowClear && !!value

    return (
        <LemonMenu
            items={items}
            tooltipPlacement={optionTooltipPlacement}
            matchWidth={dropdownMatchSelectWidth}
            placement={dropdownPlacement}
            className={menu?.className}
            maxContentWidth={dropdownMaxContentWidth}
            activeItemIndex={items
                .flatMap((i) => (isLemonMenuSection(i) ? i.items.filter(Boolean) : i))
                .findIndex((i) => (i as LemonMenuItem).active)}
            closeParentPopoverOnClickInside={menu?.closeParentPopoverOnClickInside}
            visible={visible}
            startVisible={startVisible}
        >
            <LemonButton
                className={clsx(className, 'LemonSelect')}
                icon={activeLeaf?.icon}
                type="secondary"
                sideAction={
                    isClearButtonShown
                        ? {
                              icon: <IconX />,
                              divider: false,
                              onClick: () => {
                                  onChange?.(null as T)
                              },
                          }
                        : null
                }
                sideIcon={
                    !isClearButtonShown
                        ? (activeLeaf?.sideIcon as never) // This is necessary to satisfy TS that sideIcon and sideAction ARE mutually exclusive in practice
                        : undefined
                }
                tooltip={activeLeaf?.tooltip}
                accessControl={accessControl}
                {...buttonProps}
            >
                <span className="flex flex-1">
                    {renderButtonContent
                        ? renderButtonContent(activeLeaf)
                        : activeLeaf
                          ? activeLeaf.label
                          : (value ?? placeholder)}
                </span>
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
    onSelect: NonNullable<LemonSelectPropsBase<T>['onSelect']>
): [(LemonMenuItem | LemonMenuSection)[], LemonSelectOptionLeaf<T>[]] {
    const leafOptionsAccumulator: LemonSelectOptionLeaf<T>[] = []
    const items = options
        .map((option) => convertToMenuSingle(option, activeValue, onSelect, leafOptionsAccumulator))
        .filter(Boolean) as (LemonMenuItem | LemonMenuSection)[]
    return [items, leafOptionsAccumulator]
}

function convertToMenuSingle<T>(
    option: LemonSelectOption<T> | LemonSelectSection<T>,
    activeValue: T | null,
    onSelect: NonNullable<LemonSelectPropsBase<T>['onSelect']>,
    acc: LemonSelectOptionLeaf<T>[]
): LemonMenuItem | LemonMenuSection | null {
    if (isLemonSelectSection(option)) {
        const { options: childOptions, ...section } = option
        const items = option.options.map((o) => convertToMenuSingle(o, activeValue, onSelect, acc)).filter(Boolean)
        if (!items.length) {
            // Add hidden options to the accumulator (by calling convertToMenuSingle), but don't show
            return null
        }
        return {
            ...section,
            items,
        } as LemonMenuSection
    } else if (isLemonSelectOptionNode(option)) {
        const { options: childOptions, ...node } = option
        const items = childOptions.map((o) => convertToMenuSingle(o, activeValue, onSelect, acc)).filter(Boolean)
        if (option.hidden) {
            // Add hidden options to the accumulator (by calling convertToMenuSingle), but don't show
            return null
        }
        return {
            ...node,
            active: doOptionsContainActiveValue(childOptions, activeValue),
            items,
            custom: doOptionsContainCustomControl(childOptions),
        } as LemonMenuItemNode
    }
    acc.push(option)
    if (option.hidden) {
        // Add hidden options to the accumulator, but don't show
        return null
    }
    const { value, label, labelInMenu, ...leaf } = option
    let CustomControl: LemonSelectCustomControl<T> | undefined
    if (typeof labelInMenu === 'function') {
        CustomControl = labelInMenu
    }
    return {
        ...leaf,
        label: CustomControl
            ? function LabelWrapped() {
                  if (!CustomControl) {
                      throw new Error('CustomControl became undefined')
                  }
                  return <CustomControl onSelect={onSelect} />
              }
            : labelInMenu || label,
        active: value === activeValue,
        onClick: () => onSelect(value),
    } as LemonMenuItemLeaf
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

function doOptionsContainActiveValue<T>(options: LemonSelectOptions<T>, activeValue: T | null): boolean {
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

function doOptionsContainCustomControl<T>(options: LemonSelectOptions<T>): boolean {
    for (const option of options) {
        if ('options' in option) {
            if (doOptionsContainCustomControl(option.options)) {
                return true
            }
        } else if (typeof option.labelInMenu === 'function') {
            return true
        }
    }
    return false
}
