'use client'

import * as ContextMenuPrimitive from '@radix-ui/react-context-menu'
import * as React from 'react'

// eslint-disable-next-line no-console
console.info('[memlens-stub] ContextMenu (all exports) stubbed — content returns null')

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

const ContextMenu = RenderChildrenOnly as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Root>
>
const ContextMenuSub = RenderChildrenOnly as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Sub>
>
const ContextMenuTrigger = RenderFirstChild as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Trigger>
>
const ContextMenuSubTrigger = RenderFirstChild as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.SubTrigger> & { inset?: boolean }
>
const ContextMenuContent = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Content>
>
const ContextMenuSubContent = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.SubContent>
>
const ContextMenuItem = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Item> & { inset?: boolean }
>
const ContextMenuCheckboxItem = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.CheckboxItem>
>
const ContextMenuRadioItem = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.RadioItem>
>
const ContextMenuLabel = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Label> & { inset?: boolean }
>
const ContextMenuSeparator = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Separator>
>
const ContextMenuShortcut = RenderNothing as unknown as Stub<React.HTMLAttributes<HTMLSpanElement>>
const ContextMenuGroup = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Group>
>
const ContextMenuPortal = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Portal>
>
const ContextMenuRadioGroup = RenderNothing as unknown as Stub<
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.RadioGroup>
>

export {
    ContextMenu,
    ContextMenuCheckboxItem,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuLabel,
    ContextMenuPortal,
    ContextMenuRadioGroup,
    ContextMenuRadioItem,
    ContextMenuSeparator,
    ContextMenuShortcut,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
    ContextMenuTrigger,
}
