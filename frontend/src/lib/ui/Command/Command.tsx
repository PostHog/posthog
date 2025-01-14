'use client'

import { IconSearch } from '@posthog/icons'
import { Command as CommandPrimitive } from 'cmdk'
import { cn } from 'lib/utils/styles'
import * as React from 'react'

import { Button } from '../Button/Button'
import { Input } from '../Form/Input'

const Command = React.forwardRef<
    React.ElementRef<typeof CommandPrimitive>,
    React.ComponentPropsWithoutRef<typeof CommandPrimitive>
>(
    ({ className, ...props }, ref): JSX.Element => (
        <CommandPrimitive
            ref={ref}
            className={cn('flex h-full w-full flex-col rounded-md bg-popover text-popover-foreground', className)}
            {...props}
        />
    )
)
Command.displayName = CommandPrimitive.displayName

const CommandInput = React.forwardRef<
    React.ElementRef<typeof CommandPrimitive.Input>,
    React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input> & {
        id: string // we need this to clear the input when the user clicks the clear button
    }
>(
    ({ className, children, id, ...props }, ref): JSX.Element => (
        <div cmdk-input-wrapper="">
            <CommandPrimitive.Input ref={ref} className={className} {...props} asChild>
                <Input type="text" iconLeft={<IconSearch />} clearable id={id} />
            </CommandPrimitive.Input>
        </div>
    )
)

CommandInput.displayName = CommandPrimitive.Input.displayName

const CommandList = React.forwardRef<
    React.ElementRef<typeof CommandPrimitive.List>,
    React.ComponentPropsWithoutRef<typeof CommandPrimitive.List>
>(
    ({ className, ...props }, ref): JSX.Element => (
        <CommandPrimitive.List
            ref={ref}
            className={cn('max-h-[300px] overflow-y-auto overflow-x-hidden', className)}
            {...props}
        />
    )
)

CommandList.displayName = CommandPrimitive.List.displayName

const CommandEmpty = React.forwardRef<
    React.ElementRef<typeof CommandPrimitive.Empty>,
    React.ComponentPropsWithoutRef<typeof CommandPrimitive.Empty>
>((props, ref): JSX.Element => <CommandPrimitive.Empty ref={ref} className="py-6 text-center text-sm" {...props} />)

CommandEmpty.displayName = CommandPrimitive.Empty.displayName

const CommandGroup = React.forwardRef<
    React.ElementRef<typeof CommandPrimitive.Group>,
    React.ComponentPropsWithoutRef<typeof CommandPrimitive.Group>
>(
    ({ className, ...props }, ref): JSX.Element => (
        <CommandPrimitive.Group
            ref={ref}
            className={cn(
                'text-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground',
                className
            )}
            {...props}
        />
    )
)

CommandGroup.displayName = CommandPrimitive.Group.displayName

const CommandSeparator = React.forwardRef<
    React.ElementRef<typeof CommandPrimitive.Separator>,
    React.ComponentPropsWithoutRef<typeof CommandPrimitive.Separator>
>(
    ({ className, ...props }, ref): JSX.Element => (
        <CommandPrimitive.Separator ref={ref} className={cn('-mx-1 h-px bg-border', className)} {...props} />
    )
)
CommandSeparator.displayName = CommandPrimitive.Separator.displayName

const CommandItem = React.forwardRef<
    React.ElementRef<typeof CommandPrimitive.Item>,
    React.ComponentPropsWithoutRef<typeof CommandPrimitive.Item> & {
        buttonProps?: Omit<React.ComponentPropsWithoutRef<typeof Button>, 'children'>
    }
>(
    ({ className, buttonProps = { iconRight: undefined }, children, ...props }, ref): JSX.Element => (
        <CommandPrimitive.Item
            ref={ref}
            className={cn(
                'relative flex gap-2 select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none data-[disabled=true]:pointer-events-none data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground data-[disabled=true]:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0',
                className
            )}
            asChild
            {...props}
        >
            <Button
                intent="muted"
                className="w-full"
                {...{
                    ...buttonProps,
                    size: 'base',
                }}
            >
                {children}
            </Button>
        </CommandPrimitive.Item>
    )
)

CommandItem.displayName = CommandPrimitive.Item.displayName

const CommandShortcut = ({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>): JSX.Element => {
    return <span className={cn('ml-auto text-xs tracking-widest text-muted-foreground', className)} {...props} />
}
CommandShortcut.displayName = 'CommandShortcut'

export {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
    CommandSeparator,
    CommandShortcut,
}
