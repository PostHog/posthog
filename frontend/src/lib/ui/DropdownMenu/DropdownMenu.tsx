import { IconCheck } from '@posthog/icons'
import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'
import * as React from 'react'

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
    return <DropdownMenuPrimitive.Group ref={ref} className={cn('flex flex-col gap-px', className)} {...props} />
})
DropdownMenuGroup.displayName = DropdownMenuPrimitive.Group.displayName

const DropdownMenuPortal = DropdownMenuPrimitive.Portal

const DropdownMenuSub = DropdownMenuPrimitive.Sub

const DropdownMenuRadioGroup = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.RadioGroup>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.RadioGroup>
>(({ className, ...props }, ref): JSX.Element => {
    return <DropdownMenuPrimitive.RadioGroup ref={ref} className={cn('flex flex-col gap-px', className)} {...props} />
})
DropdownMenuRadioGroup.displayName = DropdownMenuPrimitive.RadioGroup.displayName

const DropdownMenuItemIndicator = React.forwardRef<
    React.ElementRef<typeof DropdownMenuPrimitive.ItemIndicator>,
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.ItemIndicator> & {
        intent: 'checkbox' | 'radio'
    }
>(({ className, intent, ...props }, ref): JSX.Element => {
    const classes = {
        checkbox: '',
        radio: 'relative',
    }
    return (
        <div className="size-4">
            <DropdownMenuPrimitive.ItemIndicator ref={ref} className={cn(classes[intent], className)} {...props}>
                {intent === 'checkbox' && <IconCheck />}
                {intent === 'radio' && (
                    <div className="absolute left-1/2 top-1/2 -translate-y-1/2 -translate-x-1/2 h-2 w-2 rounded-full bg-black dark:bg-white" />
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
            collisionPadding = { top: 50, bottom: 50 },
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
}
