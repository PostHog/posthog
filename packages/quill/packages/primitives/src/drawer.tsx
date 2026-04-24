import { Drawer as DrawerPrimitive } from '@base-ui/react/drawer'
import * as React from 'react'

import './drawer.css'
import { cn } from './lib/utils'

function Drawer({ ...props }: DrawerPrimitive.Root.Props): React.ReactElement {
    return <DrawerPrimitive.Root data-slot="drawer" {...props} />
}

function DrawerTrigger({ ...props }: DrawerPrimitive.Trigger.Props): React.ReactElement {
    return <DrawerPrimitive.Trigger data-slot="drawer-trigger" {...props} />
}

function DrawerPortal({ ...props }: DrawerPrimitive.Portal.Props): React.ReactElement {
    return <DrawerPrimitive.Portal data-slot="drawer-portal" {...props} />
}

function DrawerClose({ ...props }: DrawerPrimitive.Close.Props): React.ReactElement {
    return <DrawerPrimitive.Close data-slot="drawer-close" {...props} />
}

function DrawerBackdrop({ className, ...props }: DrawerPrimitive.Backdrop.Props): React.ReactElement {
    return (
        <DrawerPrimitive.Backdrop
            data-slot="drawer-backdrop"
            className={cn('quill-drawer__backdrop', className)}
            {...props}
        />
    )
}

function DrawerContent({
    className,
    children,
    ...props
}: DrawerPrimitive.Popup.Props): React.ReactElement {
    return (
        <DrawerPortal>
            <DrawerBackdrop />
            <DrawerPrimitive.Viewport data-slot="drawer-viewport" className="quill-drawer__viewport">
                <DrawerPrimitive.Popup
                    data-quill
                    data-slot="drawer-content"
                    className={cn('quill-drawer__content group/drawer-content flex h-auto flex-col', className)}
                    {...props}
                >
                    <DrawerHandle />
                    <div className="w-full max-w-[32rem] mx-auto">
                    {children}
                    </div>
                </DrawerPrimitive.Popup>
            </DrawerPrimitive.Viewport>
        </DrawerPortal>
    )
}

function DrawerHandle({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="drawer-handle"
            aria-hidden="true"
            className={cn('quill-drawer__handle', className)}
            {...props}
        />
    )
}

function DrawerHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="drawer-header"
            className={cn('quill-drawer__header flex flex-col gap-1 p-4', className)}
            {...props}
        />
    )
}

function DrawerFooter({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="drawer-footer"
            className={cn('quill-drawer__footer mt-auto flex flex-col gap-2 p-4', className)}
            {...props}
        />
    )
}

function DrawerTitle({ className, ...props }: DrawerPrimitive.Title.Props): React.ReactElement {
    return (
        <DrawerPrimitive.Title
            data-slot="drawer-title"
            className={cn('quill-drawer__title', className)}
            {...props}
        />
    )
}

function DrawerDescription({ className, ...props }: DrawerPrimitive.Description.Props): React.ReactElement {
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
    DrawerBackdrop,
    DrawerTrigger,
    DrawerClose,
    DrawerContent,
    DrawerHandle,
    DrawerHeader,
    DrawerFooter,
    DrawerTitle,
    DrawerDescription,
}
