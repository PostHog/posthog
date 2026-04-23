import * as React from 'react'
import { Drawer as DrawerPrimitive } from 'vaul'

import './drawer.css'
import { cn } from './lib/utils'

function Drawer({ ...props }: React.ComponentProps<typeof DrawerPrimitive.Root>): React.ReactElement {
    return <DrawerPrimitive.Root data-slot="drawer" {...props} />
}

function DrawerTrigger({ ...props }: React.ComponentProps<typeof DrawerPrimitive.Trigger>): React.ReactElement {
    return <DrawerPrimitive.Trigger data-slot="drawer-trigger" {...props} />
}

function DrawerPortal({ ...props }: React.ComponentProps<typeof DrawerPrimitive.Portal>): React.ReactElement {
    return <DrawerPrimitive.Portal data-slot="drawer-portal" {...props} />
}

function DrawerClose({ ...props }: React.ComponentProps<typeof DrawerPrimitive.Close>): React.ReactElement {
    return <DrawerPrimitive.Close data-slot="drawer-close" {...props} />
}

function DrawerOverlay({
    className,
    ...props
}: React.ComponentProps<typeof DrawerPrimitive.Overlay>): React.ReactElement {
    return (
        <DrawerPrimitive.Overlay
            data-slot="drawer-overlay"
            className={cn(
                'quill-drawer__overlay data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0',
                className
            )}
            {...props}
        />
    )
}

function DrawerContent({
    className,
    children,
    ...props
}: React.ComponentProps<typeof DrawerPrimitive.Content>): React.ReactElement {
    return (
        <DrawerPortal data-slot="drawer-portal">
            <DrawerOverlay />
            <DrawerPrimitive.Content
                data-quill
                data-slot="drawer-content"
                className={cn('quill-drawer__content group/drawer-content flex h-auto flex-col', className)}
                {...props}
            >
                <div className="quill-drawer__handle" />
                {children}
            </DrawerPrimitive.Content>
        </DrawerPortal>
    )
}

function DrawerHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="drawer-header"
            className={cn(
                'flex flex-col gap-1 p-4 group-data-[vaul-drawer-direction=bottom]/drawer-content:text-center group-data-[vaul-drawer-direction=top]/drawer-content:text-center md:text-start',
                className
            )}
            {...props}
        />
    )
}

function DrawerFooter({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="drawer-footer" className={cn('mt-auto flex flex-col gap-2 p-4', className)} {...props} />
}

function DrawerTitle({ className, ...props }: React.ComponentProps<typeof DrawerPrimitive.Title>): React.ReactElement {
    return (
        <DrawerPrimitive.Title data-slot="drawer-title" className={cn('quill-drawer__title', className)} {...props} />
    )
}

function DrawerDescription({
    className,
    ...props
}: React.ComponentProps<typeof DrawerPrimitive.Description>): React.ReactElement {
    return (
        <DrawerPrimitive.Description
            data-slot="drawer-description"
            className={cn('quill-drawer__description', className)}
            {...props}
        />
    )
}

export {
    Drawer,
    DrawerPortal,
    DrawerOverlay,
    DrawerTrigger,
    DrawerClose,
    DrawerContent,
    DrawerHeader,
    DrawerFooter,
    DrawerTitle,
    DrawerDescription,
}
