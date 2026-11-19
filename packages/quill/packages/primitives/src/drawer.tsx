import { Drawer as DrawerPrimitive } from '@base-ui/react/drawer'
import * as React from 'react'

import './drawer.css'
import { cn } from './lib/utils'

function Drawer({ ...props }: DrawerPrimitive.Root.Props): React.ReactElement {
    return <DrawerPrimitive.Root data-slot="drawer" {...props} />
}

const DrawerTrigger = React.forwardRef<HTMLButtonElement, DrawerPrimitive.Trigger.Props>(
    function DrawerTrigger(props, ref) {
        return <DrawerPrimitive.Trigger ref={ref} data-slot="drawer-trigger" {...props} />
    }
)

function DrawerPortal({ ...props }: DrawerPrimitive.Portal.Props): React.ReactElement {
    return <DrawerPrimitive.Portal data-slot="drawer-portal" {...props} />
}

const DrawerClose = React.forwardRef<React.ComponentRef<typeof DrawerPrimitive.Close>, DrawerPrimitive.Close.Props>(
    function DrawerClose({ ...props }, ref) {
        return <DrawerPrimitive.Close ref={ref} data-slot="drawer-close" {...props} />
    }
)

const DrawerBackdrop = React.forwardRef<
    React.ComponentRef<typeof DrawerPrimitive.Backdrop>,
    DrawerPrimitive.Backdrop.Props
>(function DrawerBackdrop({ className, ...props }, ref) {
    return (
        <DrawerPrimitive.Backdrop
            ref={ref}
            data-quill
            data-quill-portal="drawer-backdrop"
            data-slot="drawer-backdrop"
            className={cn('quill-drawer__backdrop', className)}
            {...props}
        />
    )
})

const DrawerContent = React.forwardRef<React.ComponentRef<typeof DrawerPrimitive.Popup>, DrawerPrimitive.Popup.Props>(
    function DrawerContent({ className, children, ...props }, ref) {
        return (
            <DrawerPortal>
                <DrawerBackdrop />
                <DrawerPrimitive.Viewport
                    data-quill
                    data-quill-portal="drawer-viewport"
                    data-slot="drawer-viewport"
                    className="quill-drawer__viewport"
                >
                    <DrawerPrimitive.Popup
                        ref={ref}
                        data-quill
                        data-slot="drawer-content"
                        className={cn('quill-drawer__content group/drawer-content flex h-auto flex-col', className)}
                        {...props}
                    >
                        <DrawerHandle />
                        <div className="w-full max-w-[32rem] mx-auto">{children}</div>
                    </DrawerPrimitive.Popup>
                </DrawerPrimitive.Viewport>
            </DrawerPortal>
        )
    }
)

const DrawerHandle = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function DrawerHandle(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="drawer-handle"
            aria-hidden="true"
            className={cn('quill-drawer__handle', className)}
            {...props}
        />
    )
})

const DrawerHeader = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function DrawerHeader(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="drawer-header"
            className={cn('quill-drawer__header flex flex-col gap-1 p-4', className)}
            {...props}
        />
    )
})

const DrawerFooter = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function DrawerFooter(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="drawer-footer"
            className={cn('quill-drawer__footer mt-auto flex flex-col gap-2 p-4', className)}
            {...props}
        />
    )
})

const DrawerTitle = React.forwardRef<React.ComponentRef<typeof DrawerPrimitive.Title>, DrawerPrimitive.Title.Props>(
    function DrawerTitle({ className, ...props }, ref) {
        return (
            <DrawerPrimitive.Title
                ref={ref}
                data-slot="drawer-title"
                className={cn('quill-drawer__title', className)}
                {...props}
            />
        )
    }
)

const DrawerDescription = React.forwardRef<
    React.ComponentRef<typeof DrawerPrimitive.Description>,
    DrawerPrimitive.Description.Props
>(function DrawerDescription({ className, ...props }, ref) {
    return (
        <DrawerPrimitive.Description
            ref={ref}
            data-slot="drawer-description"
            className={cn('quill-drawer__description', className)}
            {...props}
        />
    )
})

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
