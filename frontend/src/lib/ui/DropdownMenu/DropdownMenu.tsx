import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu'
import * as React from 'react'

import { IconCheck } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'

import { Label } from '../Label/Label'
import { MenuSeparator } from '../Menus/Menus'

/* -------------------------------------------------------------------------- */
/*                           Button Context & Hook                            */
/* -------------------------------------------------------------------------- */

const DropdownMenu = DropdownMenuPrimitive.Root

const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger

const DropdownMenuGroup = ({
    ref,
    className,
    ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Group>): JSX.Element => {
    return <DropdownMenuPrimitive.Group ref={ref} className={cn('flex flex-col gap-px p-1', className)} {...props} />
}
DropdownMenuGroup.displayName = DropdownMenuPrimitive.Group.displayName

const DropdownMenuPortal = DropdownMenuPrimitive.Portal

const DropdownMenuSub = DropdownMenuPrimitive.Sub

const DropdownMenuRadioGroup = ({
    ref,
    className,
    ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.RadioGroup>): JSX.Element => {
    return (
        <DropdownMenuPrimitive.RadioGroup ref={ref} className={cn('flex flex-col gap-px p-1', className)} {...props} />
    )
}
DropdownMenuRadioGroup.displayName = DropdownMenuPrimitive.RadioGroup.displayName

interface DropdownMenuItemIndicatorProps extends React.ComponentProps<typeof DropdownMenuPrimitive.ItemIndicator> {
    intent: 'checkbox' | 'radio'
}

const DropdownMenuItemIndicator = ({
    ref,
    className,
    intent,
    ...props
}: DropdownMenuItemIndicatorProps): JSX.Element => {
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
}
DropdownMenuItemIndicator.displayName = DropdownMenuPrimitive.ItemIndicator.displayName

interface DropdownMenuSubTriggerProps extends React.ComponentProps<typeof DropdownMenuPrimitive.SubTrigger> {
    inset?: boolean
}

const DropdownMenuSubTrigger = ({ ref, className, inset, ...props }: DropdownMenuSubTriggerProps): JSX.Element => {
    return <DropdownMenuPrimitive.SubTrigger ref={ref} className={cn(inset && 'pl-7', className)} {...props} />
}
DropdownMenuSubTrigger.displayName = DropdownMenuPrimitive.SubTrigger.displayName

const DropdownMenuSubContent = ({
    ref,
    className,
    children,
    collisionPadding = { top: 50, bottom: 50 },
    ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.SubContent>): JSX.Element => (
    <DropdownMenuPrimitive.SubContent
        ref={ref}
        collisionPadding={collisionPadding}
        className={cn('primitive-menu-content max-h-[var(--radix-dropdown-menu-content-available-height)]', className)}
        {...props}
    >
        <ScrollableShadows direction="vertical" styledScrollbars innerClassName="primitive-menu-content-inner">
            {children}
        </ScrollableShadows>
    </DropdownMenuPrimitive.SubContent>
)
DropdownMenuSubContent.displayName = DropdownMenuPrimitive.SubContent.displayName

interface DropdownMenuContentProps extends React.ComponentProps<typeof DropdownMenuPrimitive.Content> {
    matchTriggerWidth?: boolean
}

const DropdownMenuContent = ({
    ref,
    className,
    children,
    sideOffset = 4,
    collisionPadding = { top: 50, bottom: 50, left: 10, right: 10 },
    matchTriggerWidth,
    ...props
}: DropdownMenuContentProps): JSX.Element => {
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
                <ScrollableShadows direction="vertical" styledScrollbars innerClassName="primitive-menu-content-inner">
                    {children}
                </ScrollableShadows>
            </DropdownMenuPrimitive.Content>
        </DropdownMenuPrimitive.Portal>
    )
}
DropdownMenuContent.displayName = DropdownMenuPrimitive.Content.displayName

interface DropdownMenuItemProps extends React.ComponentProps<typeof DropdownMenuPrimitive.Item> {
    inset?: boolean
}

const DropdownMenuItem = ({ ref, className, inset, ...props }: DropdownMenuItemProps): JSX.Element => {
    return <DropdownMenuPrimitive.Item ref={ref} className={cn(inset && 'pl-7', className)} {...props} />
}
DropdownMenuItem.displayName = DropdownMenuPrimitive.Item.displayName

const DropdownMenuCheckboxItem = ({
    ref,
    className,
    checked,
    ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.CheckboxItem>): JSX.Element => {
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
}
DropdownMenuCheckboxItem.displayName = DropdownMenuPrimitive.CheckboxItem.displayName

const DropdownMenuRadioItem = ({
    ref,
    className,
    ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.RadioItem>): JSX.Element => {
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
}
DropdownMenuRadioItem.displayName = DropdownMenuPrimitive.RadioItem.displayName

interface DropdownMenuLabelProps extends React.ComponentProps<typeof DropdownMenuPrimitive.Label> {
    inset?: boolean
}

const DropdownMenuLabel = ({ ref, className, inset, children, ...props }: DropdownMenuLabelProps): JSX.Element => (
    <DropdownMenuPrimitive.Label ref={ref} className={cn('px-2', inset && 'pl-7', className)} asChild {...props}>
        <Label intent="menu">{children}</Label>
    </DropdownMenuPrimitive.Label>
)
DropdownMenuLabel.displayName = DropdownMenuPrimitive.Label.displayName

const DropdownMenuSeparator = ({
    ref,
    className,
    ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Separator>): JSX.Element => (
    <DropdownMenuPrimitive.Separator ref={ref} {...props} asChild>
        <MenuSeparator className={className} />
    </DropdownMenuPrimitive.Separator>
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
