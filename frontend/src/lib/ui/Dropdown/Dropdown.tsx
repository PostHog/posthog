'use client'

import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu'
// import { Check, ChevronRight, Circle } from "lucide-react"
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/styles'
import * as React from 'react'

import { Button } from '../Button/Button'

const DropdownMenu = DropdownMenuPrimitive.Root

const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger

const DropdownMenuGroup = DropdownMenuPrimitive.Group

const DropdownMenuPortal = DropdownMenuPrimitive.Portal

const DropdownMenuSub = DropdownMenuPrimitive.Sub

const DropdownMenuRadioGroup = DropdownMenuPrimitive.RadioGroup

const DropdownMenuSubTrigger = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.SubTrigger>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubTrigger> & {
        inset?: boolean
        buttonProps?: Omit<React.ComponentPropsWithoutRef<typeof Button>, 'children'>
    }
>(
    ({ className, inset, children, buttonProps = { iconRight: undefined }, ...props }, ref): JSX.Element => (
        <DropdownMenuPrimitive.SubTrigger
            ref={ref}
            className={cn(
                'relative cursor-default select-none items-center gap-2 transition-colors data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&>svg]:size-6 [&>svg]:shrink-0',
                inset && 'pl-8',
                className
            )}
            {...props}
        >
            <Button
                intent="muted"
                className="w-full"
                {...{
                    ...buttonProps,
                    hasIcon: true,
                    size: 'sm',
                    iconRight: buttonProps.iconRight ? buttonProps.iconRight : <IconChevronRight />,
                }}
            >
                {children}
            </Button>
        </DropdownMenuPrimitive.SubTrigger>
    )
)
DropdownMenuSubTrigger.displayName = DropdownMenuPrimitive.SubTrigger.displayName

const DropdownMenuSubContent = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.SubContent>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubContent>
>(
    ({ className, ...props }, ref): JSX.Element => (
        <DropdownMenuPrimitive.SubContent
            ref={ref}
            className={cn(
                'token-border-primary token-surface-primary token-content-primary token-shadow-primary',
                'z-50 min-w-[8rem] overflow-hidden rounded border p-1',
                'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2',
                className
            )}
            {...props}
        />
    )
)
DropdownMenuSubContent.displayName = DropdownMenuPrimitive.SubContent.displayName

const DropdownMenuContent = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>
>(
    ({ className, sideOffset = 4, ...props }, ref): JSX.Element => (
        <DropdownMenuPrimitive.Portal>
            <DropdownMenuPrimitive.Content
                ref={ref}
                sideOffset={sideOffset}
                className={cn(
                    'token-border-primary token-surface-primary token-content-primary token-shadow-primary',
                    'z-50 min-w-[8rem] overflow-hidden rounded border p-1',
                    'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2',
                    className
                )}
                {...props}
            />
        </DropdownMenuPrimitive.Portal>
    )
)
DropdownMenuContent.displayName = DropdownMenuPrimitive.Content.displayName

const DropdownMenuItem = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.Item>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & {
        inset?: boolean
        buttonProps?: Omit<React.ComponentPropsWithoutRef<typeof Button>, 'children'>
    }
>(
    ({ className, inset, children, buttonProps, ...props }, ref): JSX.Element => (
        <DropdownMenuPrimitive.Item
            ref={ref}
            className={cn(
                'relative cursor-default select-none items-center gap-2 transition-colors data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&>svg]:size-6 [&>svg]:shrink-0',
                inset && 'pl-8',
                className
            )}
            asChild
            {...props}
        >
            <Button intent="muted" className="w-full" {...{ ...buttonProps, size: 'sm' }}>
                {children}
            </Button>
        </DropdownMenuPrimitive.Item>
    )
)
DropdownMenuItem.displayName = DropdownMenuPrimitive.Item.displayName

// const DropdownMenuCheckboxItem = React.forwardRef<
//   React.ElementRef<typeof DropdownMenuPrimitive.CheckboxItem>,
//   React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.CheckboxItem>
// >(({ className, children, checked, ...props }, ref): JSX.Element => (
//   <DropdownMenuPrimitive.CheckboxItem
//     ref={ref}
//     className={cn(
//       "relative flex cursor-default select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none transition-colors focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
//       className
//     )}
//     checked={checked}
//     {...props}
//   >
//     {/* <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
//       <DropdownMenuPrimitive.ItemIndicator>
//         <IconCheck className="h-4 w-4" />
//       </DropdownMenuPrimitive.ItemIndicator>
//     </span> */}
//     {children}
//   </DropdownMenuPrimitive.CheckboxItem>
// ))
// DropdownMenuCheckboxItem.displayName =
//   DropdownMenuPrimitive.CheckboxItem.displayName

// const DropdownMenuRadioItem = React.forwardRef<
//   React.ElementRef<typeof DropdownMenuPrimitive.RadioItem>,
//   React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.RadioItem>
// >(({ className, children, ...props }, ref): JSX.Element => (
//   <DropdownMenuPrimitive.RadioItem
//     ref={ref}
//     className={cn(
//       "relative flex cursor-default select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none transition-colors focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
//       className
//     )}
//     {...props}
//   >
//     {/* <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
//       <DropdownMenuPrimitive.ItemIndicator>
//         <Circle className="h-2 w-2 fill-current" />
//       </DropdownMenuPrimitive.ItemIndicator>
//     </span> */}
//     {children}
//   </DropdownMenuPrimitive.RadioItem>
// ))
// DropdownMenuRadioItem.displayName = DropdownMenuPrimitive.RadioItem.displayName

const DropdownMenuLabel = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.Label>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Label> & {
        inset?: boolean
    }
>(
    ({ className, inset, ...props }, ref): JSX.Element => (
        <DropdownMenuPrimitive.Label
            ref={ref}
            className={cn('element-dropdown-menu-label', inset && 'pl-8', className)}
            {...props}
        />
    )
)
DropdownMenuLabel.displayName = DropdownMenuPrimitive.Label.displayName

const DropdownMenuSeparator = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.Separator>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Separator>
>(
    ({ className, ...props }, ref): JSX.Element => (
        <DropdownMenuPrimitive.Separator
            ref={ref}
            className={cn('element-dropdown-menu-separator', className)}
            {...props}
        />
    )
)
DropdownMenuSeparator.displayName = DropdownMenuPrimitive.Separator.displayName

const DropdownMenuShortcut = ({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>): JSX.Element => {
    return <span className={cn('ml-auto text-xs tracking-widest opacity-60', className)} {...props} />
}
DropdownMenuShortcut.displayName = 'DropdownMenuShortcut'

const DropdownMenuFooter = React.forwardRef<HTMLElement, React.HTMLAttributes<HTMLElement>>(
    ({ className, ...props }, ref): JSX.Element => (
        <footer ref={ref} className={cn('element-dropdown-menu-footer', className)} {...props} />
    )
)
DropdownMenuFooter.displayName = 'DropdownMenuFooter'

export {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuFooter,
    DropdownMenuGroup,
    DropdownMenuItem,
    // DropdownMenuCheckboxItem,
    // DropdownMenuRadioItem,
    DropdownMenuLabel,
    DropdownMenuPortal,
    DropdownMenuRadioGroup,
    DropdownMenuSeparator,
    DropdownMenuShortcut,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
}
