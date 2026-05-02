import { Select as SelectPrimitive } from '@base-ui/react/select'
import { ChevronDownIcon, ChevronUpIcon, CheckIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'
import { MenuLabel } from './menu-label'
import './select.css'

const Select = SelectPrimitive.Root

function SelectGroup({ className, ...props }: SelectPrimitive.Group.Props): React.ReactElement {
    return <SelectPrimitive.Group data-slot="select-group" className={cn('quill-select__group', className)} {...props} />
}

function SelectValue({ className, ...props }: SelectPrimitive.Value.Props): React.ReactElement {
    return <SelectPrimitive.Value data-slot="select-value" className={cn('quill-select__value', className)} {...props} />
}

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
            <SelectPrimitive.Icon render={<ChevronDownIcon className="quill-select__icon" />} />
        </SelectPrimitive.Trigger>
    )
}

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
                    className={cn(
                        'quill-select__content',
                        className
                    )}
                    {...props}
                >
                    <SelectScrollUpButton />
                    <SelectPrimitive.List>{children}</SelectPrimitive.List>
                    <SelectScrollDownButton />
                </SelectPrimitive.Popup>
            </SelectPrimitive.Positioner>
        </SelectPrimitive.Portal>
    )
}

function SelectGroupLabel({ className, ...props }: SelectPrimitive.GroupLabel.Props): React.ReactElement {
    return <SelectPrimitive.GroupLabel data-slot="select-label" className={className} render={<MenuLabel />} {...props} />
}

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

function SelectSeparator({ className, ...props }: SelectPrimitive.Separator.Props): React.ReactElement {
    return <SelectPrimitive.Separator data-slot="select-separator" className={cn('quill-select__separator', className)} {...props} />
}

function SelectScrollUpButton({
    className,
    ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollUpArrow>): React.ReactElement {
    return (
        <SelectPrimitive.ScrollUpArrow
            data-slot="select-scroll-up-button"
            className={cn('quill-select__scroll-button flex items-center justify-center', className)}
            {...props}
        >
            <ChevronUpIcon />
        </SelectPrimitive.ScrollUpArrow>
    )
}

function SelectScrollDownButton({
    className,
    ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollDownArrow>): React.ReactElement {
    return (
        <SelectPrimitive.ScrollDownArrow
            data-slot="select-scroll-down-button"
            className={cn('quill-select__scroll-button quill-select__scroll-button--down flex items-center justify-center', className)}
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
    SelectValue,
}
