import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu'
import * as React from 'react'

import { IconCheck, IconChevronRight } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'

import { Label } from '../Label/Label'

/* -------------------------------------------------------------------------- */
/*                           Button Context & Hook                            */
/* -------------------------------------------------------------------------- */

const DropdownMenu = DropdownMenuPrimitive.Root

const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger

const DropdownMenuGroup = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.Group>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Group>
>(({ className, ...props }, ref): JSX.Element => {
    return <DropdownMenuPrimitive.Group ref={ref} className={cn('flex flex-col gap-px p-1', className)} {...props} />
})
DropdownMenuGroup.displayName = DropdownMenuPrimitive.Group.displayName

const DropdownMenuPortal = DropdownMenuPrimitive.Portal

const DropdownMenuSub = DropdownMenuPrimitive.Sub

const DropdownMenuRadioGroup = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.RadioGroup>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.RadioGroup>
>(({ className, ...props }, ref): JSX.Element => {
    return (
        <DropdownMenuPrimitive.RadioGroup ref={ref} className={cn('flex flex-col gap-px p-1', className)} {...props} />
    )
})
DropdownMenuRadioGroup.displayName = DropdownMenuPrimitive.RadioGroup.displayName

const DropdownMenuItemIndicator = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.ItemIndicator>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.ItemIndicator> & {
        intent: 'checkbox' | 'radio'
    }
>(({ className, intent, ...props }, ref): JSX.Element => {
    return (
        // We need to make a box around the indicator to ensure when it's not "checked" it's still the same size
        <div className="flex place-items-center size-[var(--button-height)] shrink-0">
            <DropdownMenuPrimitive.ItemIndicator
                ref={ref}
                className={cn('size-full flex place-items-center shrink-0', className)}
                {...props}
            >
                {intent === 'checkbox' && <IconCheck className="shrink-0" />}
                {intent === 'radio' && (
                    <div className="h-2 w-2 rounded-full bg-black dark:bg-white relative -translate-x-1/2 left-1/2" />
                )}
            </DropdownMenuPrimitive.ItemIndicator>
        </div>
    )
})
DropdownMenuItemIndicator.displayName = DropdownMenuPrimitive.ItemIndicator.displayName

const DropdownMenuSubTrigger = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.SubTrigger>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubTrigger> & {
        inset?: boolean
    }
>(({ className, inset, ...props }, ref): JSX.Element => {
    return <DropdownMenuPrimitive.SubTrigger ref={ref} className={cn(inset && 'pl-7', className)} {...props} />
})
DropdownMenuSubTrigger.displayName = DropdownMenuPrimitive.SubTrigger.displayName

const DropdownMenuSubContent = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.SubContent>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubContent>
>(
    ({ className, children, collisionPadding = { top: 50, bottom: 50 }, ...props }, ref): JSX.Element => (
        <DropdownMenuPrimitive.SubContent
            ref={ref}
            collisionPadding={collisionPadding}
            className={cn(
                'primitive-menu-content max-h-[var(--radix-dropdown-menu-content-available-height)]',
                className
            )}
            {...props}
        >
            <ScrollableShadows direction="vertical" styledScrollbars innerClassName="primitive-menu-content-inner">
                {children}
            </ScrollableShadows>
        </DropdownMenuPrimitive.SubContent>
    )
)
DropdownMenuSubContent.displayName = DropdownMenuPrimitive.SubContent.displayName

const DropdownMenuContent = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content> & {
        matchTriggerWidth?: boolean
    }
>(
    (
        {
            className,
            children,
            sideOffset = 4,
            collisionPadding = { top: 50, bottom: 50, left: 10, right: 10 },
            matchTriggerWidth,
            ...props
        },
        ref
    ): JSX.Element => {
        return (
            <DropdownMenuPrimitive.Portal>
                <DropdownMenuPrimitive.Content
                    ref={ref}
                    sideOffset={sideOffset}
                    collisionPadding={collisionPadding}
                    className={cn(
                        'primitive-menu-content max-h-[var(--radix-dropdown-menu-content-available-height)]',
                        matchTriggerWidth && 'min-w-[var(--radix-dropdown-menu-trigger-width)]',
                        className
                    )}
                    loop
                    {...props}
                >
                    <ScrollableShadows
                        direction="vertical"
                        styledScrollbars
                        innerClassName="primitive-menu-content-inner"
                    >
                        {children}
                    </ScrollableShadows>
                </DropdownMenuPrimitive.Content>
            </DropdownMenuPrimitive.Portal>
        )
    }
)
DropdownMenuContent.displayName = DropdownMenuPrimitive.Content.displayName

const DropdownMenuItem = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.Item>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & {
        inset?: boolean
    }
>(({ className, inset, ...props }, ref): JSX.Element => {
    return <DropdownMenuPrimitive.Item ref={ref} className={cn(inset && 'pl-7', className)} {...props} />
})
DropdownMenuItem.displayName = DropdownMenuPrimitive.Item.displayName

const DropdownMenuCheckboxItem = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.CheckboxItem>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.CheckboxItem>
>(({ className, checked, ...props }, ref): JSX.Element => {
    return (
        <DropdownMenuPrimitive.CheckboxItem
            ref={ref}
            className={cn(
                'relative flex cursor-default select-none outline-none transition-colors data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
                className
            )}
            checked={checked}
            {...props}
        />
    )
})
DropdownMenuCheckboxItem.displayName = DropdownMenuPrimitive.CheckboxItem.displayName

const DropdownMenuRadioItem = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.RadioItem>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.RadioItem>
>(({ className, ...props }, ref): JSX.Element => {
    return (
        <DropdownMenuPrimitive.RadioItem
            ref={ref}
            className={cn(
                'relative flex cursor-default select-none outline-none transition-colors data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
                className
            )}
            {...props}
        />
    )
})
DropdownMenuRadioItem.displayName = DropdownMenuPrimitive.RadioItem.displayName

const DropdownMenuLabel = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.Label>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Label> & {
        inset?: boolean
    }
>(
    ({ className, inset, children, ...props }, ref): JSX.Element => (
        <DropdownMenuPrimitive.Label ref={ref} className={cn('px-2', inset && 'pl-7', className)} asChild {...props}>
            <Label intent="menu">{children}</Label>
        </DropdownMenuPrimitive.Label>
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
            className={cn('-mx-1 my-1 h-px bg-border-primary', className)}
            {...props}
        />
    )
)
DropdownMenuSeparator.displayName = DropdownMenuPrimitive.Separator.displayName

interface DropdownMenuOpenIndicatorProps extends React.HTMLAttributes<HTMLOrSVGElement> {
    intent?: 'default' | 'sub'
}
const DropdownMenuOpenIndicator = ({
    className,
    intent = 'default',
    ...props
}: DropdownMenuOpenIndicatorProps): JSX.Element => {
    return (
        <IconChevronRight
            className={cn(
                'ml-auto size-3 text-secondary rotate-90 group-data-[state=open]/button-primitive:rotate-270 transition-transform duration-200 prefers-reduced-motion:transition-none',
                intent === 'sub' && 'rotate-0 group-data-[state=open]/button-primitive:rotate-0',
                className
            )}
            {...props}
        />
    )
}
DropdownMenuOpenIndicator.displayName = 'DropdownMenuOpenIndicator'

const DropdownMenuShortcut = ({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>): JSX.Element => {
    return <span className={cn('ml-auto text-xs tracking-widest opacity-60', className)} {...props} />
}
DropdownMenuShortcut.displayName = 'DropdownMenuShortcut'

export {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuItemIndicator,
    DropdownMenuLabel,
    DropdownMenuPortal,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuShortcut,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    DropdownMenuOpenIndicator,
}
