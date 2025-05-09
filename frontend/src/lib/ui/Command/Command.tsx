import * as React from "react"
import { Command as CommandPrimitive } from "cmdk"
import { IconSearch } from "@posthog/icons"
import { cn } from "lib/utils/css-classes"

function Command({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive>): JSX.Element {
  return (
    <CommandPrimitive
      data-slot="command"
      className={cn(
        "bg-popover text-popover-foreground flex h-full w-full flex-col rounded-md relative",
        className
      )}
      {...props}
    />
  )
}

function CommandInput({
  className,
  wrapperClassName,
  showSearchIcon = true,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Input> & {
  wrapperClassName?: string;
  showSearchIcon?: boolean;
}): JSX.Element {
  return (
    <div
      data-slot="command-input-wrapper"
      className={cn(
        "LemonInput LemonInput--small flex items-center ",
        wrapperClassName
      )}
    >
      {showSearchIcon && <IconSearch className="flex items-center justify-center size-4 ml-[2px] mr-px" />}
      <CommandPrimitive.Input
        data-slot="command-input"
        className={cn(
          "LemonInput__input w-full rounded-md bg-transparent py-3 text-sm outline-hidden disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        {...props}
      />
    </div>
  )
}

function CommandList({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.List>): JSX.Element {
  return (
    <CommandPrimitive.List
      data-slot="command-list"
      className={cn(
        "primitive-menu-content max-h-[300px] scroll-py-1 overflow-x-hidden overflow-y-auto",
        className
      )}
      {...props}
    />
  )
}

function CommandEmpty({
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Empty>): JSX.Element {
  return (
    <CommandPrimitive.Empty
      data-slot="command-empty"
      className="py-6 text-center text-sm"
      {...props}
    />
  )
}

function CommandGroup({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Group>): JSX.Element {
  return (
    <CommandPrimitive.Group
      data-slot="command-group"
      className={cn(
        `
          text-left text-foreground overflow-hidden p-1 gap-px
          [&_[cmdk-group-heading]]:px-[12px]
          [&_[cmdk-group-heading]]:text-tertiary
          [&_[cmdk-group-heading]]:uppercase
          [&_[cmdk-group-heading]]:font-semibold
          [&_[cmdk-group-heading]]:text-[0.6875rem] 
          [&_[cmdk-group-heading]]:leading-5
          [&_[cmdk-group-heading]]:tracking-[0.075em]
          [&_[cmdk-group-heading]]:py-1
          [&_[cmdk-group-heading]]:border-b
          [&_[cmdk-group-heading]]:border-primary
          [&_[cmdk-group-heading]]:-mx-1
          [&_[cmdk-group-heading]]:mb-1
          ${className}
        `
      )}
      {...props}
    />
  )
}

function CommandSeparator({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Separator>): JSX.Element {
  return (
    <CommandPrimitive.Separator
      data-slot="command-separator"
      className={cn("bg-border -mx-1 h-px", className)}
      {...props}
    />
  )
}

function CommandItem({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Item>): JSX.Element {
  return (
    <CommandPrimitive.Item
      data-slot="command-item"
      className={className}
      {...props}
    />
  )
}

function CommandShortcut({
  className,
  ...props
}: React.ComponentProps<"span">): JSX.Element {
  return (
    <span
      data-slot="command-shortcut"
      className={cn(
        "text-muted-foreground ml-auto text-xs tracking-widest",
        className
      )}
      {...props}
    />
  )
}

export {
  Command,
  // CommandDialog,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandShortcut,
  CommandSeparator,
}
