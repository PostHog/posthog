import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu'
import * as React from 'react'

// eslint-disable-next-line no-console
console.info('[memlens-stub] DropdownMenu (all exports) stubbed — content returns null')

// Stubs use `any` for props so consumer inline callbacks aren't flagged as implicit-any.
// This whole file is an experiment; original types are restored when the file is.
/* eslint-disable @typescript-eslint/no-explicit-any */

function RenderChildrenOnly({ children }: { children?: React.ReactNode }): JSX.Element {
    return <>{children}</>
}

function RenderFirstChild({ children }: { children?: React.ReactNode }): JSX.Element | null {
    const only = React.Children.toArray(children).find(Boolean)
    return React.isValidElement(only) ? only : <>{children}</>
}

function RenderNothing(): null {
    return null
}

type Stub<P> = React.ComponentType<P>

// Roots pass children through so triggers still render.
const DropdownMenu = RenderChildrenOnly as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Root>
>
const DropdownMenuSub = RenderChildrenOnly as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Sub>
>

// Triggers render their child (usually asChild-style).
const DropdownMenuTrigger = RenderFirstChild as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Trigger>
>
const DropdownMenuSubTrigger = RenderFirstChild as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubTrigger> & { inset?: boolean }
>

// Everything else renders nothing.
const DropdownMenuContent = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content> & { matchTriggerWidth?: boolean }
>
const DropdownMenuSubContent = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubContent>
>
const DropdownMenuItem = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & { inset?: boolean }
>
const DropdownMenuCheckboxItem = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.CheckboxItem>
>
const DropdownMenuRadioItem = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.RadioItem>
>
const DropdownMenuItemIndicator = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.ItemIndicator> & { intent: 'checkbox' | 'radio' }
>
const DropdownMenuLabel = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Label> & { inset?: boolean }
>
const DropdownMenuSeparator = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Separator>
>
const DropdownMenuShortcut = RenderNothing as unknown as Stub<React.HTMLAttributes<HTMLSpanElement>>
const DropdownMenuGroup = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Group>
>
const DropdownMenuPortal = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Portal>
>
const DropdownMenuRadioGroup = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.RadioGroup>
>

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
