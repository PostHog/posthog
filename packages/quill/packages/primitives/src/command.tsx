import { Command as CommandPrimitive } from 'cmdk'
import { SearchIcon, CheckIcon } from 'lucide-react'
import * as React from 'react'

import './command.css'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './dialog'
import { InputGroup, InputGroupAddon } from './input-group'
import { cn } from './lib/utils'

function Command({ className, ...props }: React.ComponentProps<typeof CommandPrimitive>): React.ReactElement {
    return (
        <CommandPrimitive
            data-quill
            data-slot="command"
            className={cn('quill-command flex size-full flex-col overflow-hidden', className)}
            {...props}
        />
    )
}

function CommandDialog({
    title = 'Command Palette',
    description = 'Search for a command to run...',
    children,
    className,
    showCloseButton = false,
    ...props
}: Omit<React.ComponentProps<typeof Dialog>, 'children'> & {
    title?: string
    description?: string
    className?: string
    showCloseButton?: boolean
    children: React.ReactNode
}): React.ReactElement {
    return (
        <Dialog {...props}>
            <DialogHeader className="sr-only">
                <DialogTitle>{title}</DialogTitle>
                <DialogDescription>{description}</DialogDescription>
            </DialogHeader>
            <DialogContent
                className={cn('top-1/3 translate-y-0 overflow-hidden rounded-xl! p-0', className)}
                showCloseButton={showCloseButton}
            >
                {children}
            </DialogContent>
        </Dialog>
    )
}

function CommandInput({
    className,
    ...props
}: React.ComponentProps<typeof CommandPrimitive.Input>): React.ReactElement {
    return (
        <div data-slot="command-input-wrapper" className="p-1 pb-0">
            <InputGroup className="h-8!">
                <CommandPrimitive.Input
                    data-slot="command-input"
                    className={cn(
                        'w-full text-xs/relaxed outline-hidden disabled:cursor-not-allowed disabled:opacity-50',
                        className
                    )}
                    {...props}
                />
                <InputGroupAddon>
                    <SearchIcon className="size-3.5 shrink-0 opacity-50" />
                </InputGroupAddon>
            </InputGroup>
        </div>
    )
}

function CommandList({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.List>): React.ReactElement {
    return <CommandPrimitive.List data-slot="command-list" className={cn('quill-command__list', className)} {...props} />
}

function CommandEmpty({
    className,
    ...props
}: React.ComponentProps<typeof CommandPrimitive.Empty>): React.ReactElement {
    return <CommandPrimitive.Empty data-slot="command-empty" className={cn('quill-command__empty', className)} {...props} />
}

function CommandGroup({
    className,
    ...props
}: React.ComponentProps<typeof CommandPrimitive.Group>): React.ReactElement {
    return <CommandPrimitive.Group data-slot="command-group" className={cn('quill-command__group overflow-hidden', className)} {...props} />
}

function CommandSeparator({
    className,
    ...props
}: React.ComponentProps<typeof CommandPrimitive.Separator>): React.ReactElement {
    return <CommandPrimitive.Separator data-slot="command-separator" className={cn('quill-command__separator', className)} {...props} />
}

function CommandItem({
    className,
    children,
    ...props
}: React.ComponentProps<typeof CommandPrimitive.Item>): React.ReactElement {
    return (
        <CommandPrimitive.Item
            data-slot="command-item"
            className={cn(
                'quill-command__item group/command-item relative flex cursor-default items-center gap-2 select-none',
                className
            )}
            {...props}
        >
            {children}
            <CheckIcon className="ms-auto opacity-0 group-has-data-[slot=command-shortcut]/command-item:hidden group-data-[checked=true]/command-item:opacity-100" />
        </CommandPrimitive.Item>
    )
}

function CommandShortcut({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="command-shortcut" className={cn('quill-command__shortcut', className)} {...props} />
}

export {
    Command,
    CommandDialog,
    CommandInput,
    CommandList,
    CommandEmpty,
    CommandGroup,
    CommandItem,
    CommandShortcut,
    CommandSeparator,
}
