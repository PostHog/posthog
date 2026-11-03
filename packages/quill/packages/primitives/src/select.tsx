import './select.css'

import { Select as SelectPrimitive } from '@base-ui/react/select'
import { ChevronDownIcon, ChevronUpIcon, CheckIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'
import { MenuLabel } from './menu-label'

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
    }
>(function SelectTrigger({ className, size = 'default', children, ...props }, ref) {
    return (
        <SelectPrimitive.Trigger
            ref={ref}
            data-slot="select-trigger"
            data-size={size}
            className={cn(
                'quill-select__trigger group/select-trigger flex items-center justify-between gap-3 whitespace-nowrap outline-none',
                className
            )}
            render={<Button variant="outline" size={size} left />}
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
    } & Pick<SelectPrimitive.Positioner.Props, 'align' | 'alignOffset' | 'side' | 'sideOffset' | 'alignItemWithTrigger'>
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
        ...props
    },
    ref
) {
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

const SelectItem = React.forwardRef<React.ComponentRef<typeof SelectPrimitive.Item>, SelectPrimitive.Item.Props>(
    function SelectItem({ className, children, ...props }, ref) {
        return (
            <SelectPrimitive.Item
                ref={ref}
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
                    <CheckIcon className="quill-select__indicator-icon pointer-events-none size-3.5" />
                </SelectPrimitive.ItemIndicator>
            </SelectPrimitive.Item>
        )
    }
)

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
