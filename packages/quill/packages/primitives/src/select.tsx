import './select.css'

import { Select as SelectPrimitive } from '@base-ui/react/select'
import { ChevronDownIcon, ChevronUpIcon, CheckIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'
import { MenuLabel } from './menu-label'
import { hasTooltipContent, withTooltip } from './with-tooltip'

const Select = SelectPrimitive.Root

const SelectGroup = React.forwardRef<React.ComponentRef<typeof SelectPrimitive.Group>, SelectPrimitive.Group.Props>(
    function SelectGroup({ className, ...props }, ref) {
        return (
            <SelectPrimitive.Group
                ref={ref}
                data-slot="select-group"
                className={cn('quill-select__group', className)}
                {...props}
            />
        )
    }
)

const SelectValue = React.forwardRef<React.ComponentRef<typeof SelectPrimitive.Value>, SelectPrimitive.Value.Props>(
    function SelectValue({ className, ...props }, ref) {
        return (
            <SelectPrimitive.Value
                ref={ref}
                data-slot="select-value"
                className={cn('quill-select__value', className)}
                {...props}
            />
        )
    }
)

const SelectTriggerIcon = React.forwardRef<
    React.ComponentRef<typeof ChevronDownIcon>,
    React.ComponentProps<typeof ChevronDownIcon>
>(function SelectTriggerIcon({ className, ...props }, ref) {
    return <ChevronDownIcon ref={ref} className={cn('quill-select__icon', className)} {...props} />
})

const SelectTrigger = React.forwardRef<
    React.ComponentRef<typeof SelectPrimitive.Trigger>,
    SelectPrimitive.Trigger.Props & {
        size?: 'sm' | 'default'
        /**
         * Disables the trigger and says why in its tooltip. The trigger stays hoverable and focusable.
         * A `render` that replaces the default Button takes its own `disabledReason` instead.
         */
        disabledReason?: React.ReactNode
    }
>(function SelectTrigger({ className, size = 'default', disabledReason, children, ...props }, ref) {
    return (
        <SelectPrimitive.Trigger
            ref={ref}
            data-slot="select-trigger"
            data-size={size}
            className={cn(
                'quill-select__trigger group/select-trigger flex items-center justify-between gap-3 whitespace-nowrap outline-none',
                className
            )}
            // The Button disables itself for the reason. Disabling the trigger instead would take it out
            // of the tab order, and the reason would only open on hover.
            render={<Button variant="outline" size={size} left disabledReason={disabledReason} />}
            {...props}
        >
            {children}
            <SelectPrimitive.Icon render={<SelectTriggerIcon />} />
        </SelectPrimitive.Trigger>
    )
})

const SelectContent = React.forwardRef<
    React.ComponentRef<typeof SelectPrimitive.Popup>,
    SelectPrimitive.Popup.Props & {
        /**
         * Rendered in the positioner as the popup's sibling, escaping the popup's overflow and scroll
         * mask. Use position: absolute — in-flow content here resizes the box the positioner measures.
         */
        popupSibling?: React.ReactNode
    } & Pick<
            SelectPrimitive.Positioner.Props,
            'align' | 'alignOffset' | 'side' | 'sideOffset' | 'alignItemWithTrigger'
        > &
        Pick<SelectPrimitive.Portal.Props, 'container'>
>(function SelectContent(
    {
        className,
        children,
        popupSibling,
        side = 'bottom',
        sideOffset = 4,
        align = 'center',
        alignOffset = 0,
        alignItemWithTrigger = true,
        container,
        ...props
    },
    ref
) {
    return (
        <SelectPrimitive.Portal container={container}>
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
                {popupSibling}
                <SelectPrimitive.Popup
                    ref={ref}
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
})

const SelectGroupLabel = React.forwardRef<
    React.ComponentRef<typeof SelectPrimitive.GroupLabel>,
    SelectPrimitive.GroupLabel.Props
>(function SelectGroupLabel({ className, ...props }, ref) {
    return (
        <SelectPrimitive.GroupLabel
            ref={ref}
            data-slot="select-label"
            className={className}
            render={<MenuLabel />}
            {...props}
        />
    )
})

const SelectItem = React.forwardRef<
    React.ComponentRef<typeof SelectPrimitive.Item>,
    SelectPrimitive.Item.Props & {
        /** Disables the item and says why in a tooltip beside it. */
        disabledReason?: React.ReactNode
    }
>(function SelectItem({ className, children, disabled, disabledReason, ...props }, ref) {
    const hasReason = hasTooltipContent(disabledReason)
    const item = (
        <SelectPrimitive.Item
            ref={ref}
            data-slot="select-item"
            disabled={disabled || hasReason}
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
                <CheckIcon className="quill-select__indicator-icon pointer-events-none size-3.5" />
            </SelectPrimitive.ItemIndicator>
        </SelectPrimitive.Item>
    )
    // A disabled item ignores the pointer, so the tooltip listens on a wrapper and opens beside the row. Rows without a
    // reason skip the wrapper, so a long list does not mount one per row.
    return hasReason ? withTooltip(item, disabledReason, { target: 'block', side: 'inline-end' }) : item
})

const SelectSeparator = React.forwardRef<
    React.ComponentRef<typeof SelectPrimitive.Separator>,
    SelectPrimitive.Separator.Props
>(function SelectSeparator({ className, ...props }, ref) {
    return (
        <SelectPrimitive.Separator
            ref={ref}
            data-slot="select-separator"
            className={cn('quill-select__separator', className)}
            {...props}
        />
    )
})

const SelectScrollUpButton = React.forwardRef<
    React.ComponentRef<typeof SelectPrimitive.ScrollUpArrow>,
    React.ComponentProps<typeof SelectPrimitive.ScrollUpArrow>
>(function SelectScrollUpButton({ className, ...props }, ref) {
    return (
        <SelectPrimitive.ScrollUpArrow
            ref={ref}
            data-slot="select-scroll-up-button"
            className={cn('quill-select__scroll-button quill-select__scroll-button--up', className)}
            render={<Button variant="outline" size="icon-sm" />}
            {...props}
        >
            <ChevronUpIcon />
        </SelectPrimitive.ScrollUpArrow>
    )
})

const SelectScrollDownButton = React.forwardRef<
    React.ComponentRef<typeof SelectPrimitive.ScrollDownArrow>,
    React.ComponentProps<typeof SelectPrimitive.ScrollDownArrow>
>(function SelectScrollDownButton({ className, ...props }, ref) {
    return (
        <SelectPrimitive.ScrollDownArrow
            ref={ref}
            data-slot="select-scroll-down-button"
            className={cn('quill-select__scroll-button quill-select__scroll-button--down', className)}
            render={<Button variant="outline" size="icon-sm" />}
            {...props}
        >
            <ChevronDownIcon />
        </SelectPrimitive.ScrollDownArrow>
    )
})

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
