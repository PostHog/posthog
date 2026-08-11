import './select.css'

import { Select as SelectPrimitive } from '@base-ui/react/select'
import { ChevronDownIcon, ChevronUpIcon, CheckIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'
import { MenuLabel } from './menu-label'

const Select = SelectPrimitive.Root

/**
 * Groups related select items with the corresponding label.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Select](https://base-ui.com/react/components/select)
 *
 * @baseui Select.Group
 */
function SelectGroup({ className, ...props }: SelectPrimitive.Group.Props): React.ReactElement {
    return (
        <SelectPrimitive.Group data-slot="select-group" className={cn('quill-select__group', className)} {...props} />
    )
}

/**
 * A text label of the currently selected item.
 * Renders a `<span>` element.
 *
 * Documentation: [Base UI Select](https://base-ui.com/react/components/select)
 *
 * @baseui Select.Value
 */
function SelectValue({ className, ...props }: SelectPrimitive.Value.Props): React.ReactElement {
    return (
        <SelectPrimitive.Value data-slot="select-value" className={cn('quill-select__value', className)} {...props} />
    )
}

function SelectTriggerIcon({ className, ...props }: React.ComponentProps<typeof ChevronDownIcon>): React.ReactElement {
    return <ChevronDownIcon className={cn('quill-select__icon', className)} {...props} />
}

/**
 * A button that opens the select popup.
 * Renders a `<button>` element.
 *
 * Documentation: [Base UI Select](https://base-ui.com/react/components/select)
 *
 * @baseui Select.Trigger
 */
function SelectTrigger({
    className,
    size = 'default',
    children,
    ...props
}: SelectPrimitive.Trigger.Props & {
    size?: 'sm' | 'default'
}): React.ReactElement {
    return (
        <SelectPrimitive.Trigger
            data-slot="select-trigger"
            data-size={size}
            className={cn(
                'quill-select__trigger group/select-trigger flex items-center justify-between gap-3 whitespace-nowrap outline-none',
                className
            )}
            render={<Button variant="outline" left />}
            {...props}
        >
            {children}
            <SelectPrimitive.Icon render={<SelectTriggerIcon />} />
        </SelectPrimitive.Trigger>
    )
}

/**
 * A container for the select list.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Select](https://base-ui.com/react/components/select)
 *
 * @baseui Select.Popup
 */
function SelectContent({
    className,
    children,
    side = 'bottom',
    sideOffset = 4,
    align = 'center',
    alignOffset = 0,
    alignItemWithTrigger = true,
    ...props
}: SelectPrimitive.Popup.Props &
    Pick<
        SelectPrimitive.Positioner.Props,
        'align' | 'alignOffset' | 'side' | 'sideOffset' | 'alignItemWithTrigger'
    >): React.ReactElement {
    return (
        <SelectPrimitive.Portal>
            <SelectPrimitive.Positioner
                data-quill
                data-quill-portal="popover"
                side={side}
                sideOffset={sideOffset}
                align={align}
                alignOffset={alignOffset}
                alignItemWithTrigger={alignItemWithTrigger}
                className="isolate"
            >
                <SelectPrimitive.Popup
                    data-slot="select-content"
                    data-align-trigger={alignItemWithTrigger}
                    className={cn('quill-select__content', className)}
                    {...props}
                >
                    <SelectScrollUpButton className="quill-select__scroll-button flex items-center justify-center" />
                    <SelectPrimitive.List className="quill-select__list scroll-mask-y-4 scroll-py-4">
                        {children}
                    </SelectPrimitive.List>
                    <SelectScrollDownButton />
                </SelectPrimitive.Popup>
            </SelectPrimitive.Positioner>
        </SelectPrimitive.Portal>
    )
}

/**
 * An accessible label that is automatically associated with its parent group.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Select](https://base-ui.com/react/components/select)
 *
 * @baseui Select.GroupLabel
 */
function SelectGroupLabel({ className, ...props }: SelectPrimitive.GroupLabel.Props): React.ReactElement {
    return (
        <SelectPrimitive.GroupLabel data-slot="select-label" className={className} render={<MenuLabel />} {...props} />
    )
}

/**
 * An individual option in the select popup.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Select](https://base-ui.com/react/components/select)
 *
 * @baseui Select.Item
 */
function SelectItem({ className, children, ...props }: SelectPrimitive.Item.Props): React.ReactElement {
    return (
        <SelectPrimitive.Item
            data-slot="select-item"
            className={cn(
                'quill-select__item group/select-item flex w-full cursor-default items-center gap-2 select-none',
                className
            )}
            {...props}
        >
            <SelectPrimitive.ItemText className="flex flex-1 shrink-0 gap-2 whitespace-nowrap">
                {children}
            </SelectPrimitive.ItemText>
            <SelectPrimitive.ItemIndicator
                render={<span className="pointer-events-none absolute end-2 flex items-center justify-center" />}
            >
                <CheckIcon className="pointer-events-none" />
            </SelectPrimitive.ItemIndicator>
        </SelectPrimitive.Item>
    )
}

/**
 * A visual separator between items or groups.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Select](https://base-ui.com/react/components/select)
 *
 * @baseui Select.Separator
 */
function SelectSeparator({ className, ...props }: SelectPrimitive.Separator.Props): React.ReactElement {
    return (
        <SelectPrimitive.Separator
            data-slot="select-separator"
            className={cn('quill-select__separator', className)}
            {...props}
        />
    )
}

/**
 * An element that scrolls the select popup up when hovered. Does not render when using touch input.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Select](https://base-ui.com/react/components/select)
 *
 * @baseui Select.ScrollUpArrow
 */
function SelectScrollUpButton({
    className,
    ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollUpArrow>): React.ReactElement {
    return (
        <SelectPrimitive.ScrollUpArrow
            data-slot="select-scroll-up-button"
            className={cn('quill-select__scroll-button quill-select__scroll-button--up', className)}
            render={<Button variant="outline" size="icon-sm" />}
            {...props}
        >
            <ChevronUpIcon />
        </SelectPrimitive.ScrollUpArrow>
    )
}

/**
 * An element that scrolls the select popup down when hovered. Does not render when using touch input.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Select](https://base-ui.com/react/components/select)
 *
 * @baseui Select.ScrollDownArrow
 */
function SelectScrollDownButton({
    className,
    ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollDownArrow>): React.ReactElement {
    return (
        <SelectPrimitive.ScrollDownArrow
            data-slot="select-scroll-down-button"
            className={cn('quill-select__scroll-button quill-select__scroll-button--down', className)}
            render={<Button variant="outline" size="icon-sm" />}
            {...props}
        >
            <ChevronDownIcon />
        </SelectPrimitive.ScrollDownArrow>
    )
}

export {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectScrollDownButton,
    SelectScrollUpButton,
    SelectSeparator,
    SelectTrigger,
    SelectTriggerIcon,
    SelectValue,
}
