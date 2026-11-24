import { Drawer as DrawerPrimitive } from '@base-ui/react/drawer'
import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import * as React from 'react'

import './drawer.css'
import { cn } from './lib/utils'
import { ScrollArea } from './scroll-area'

/** A handle also attaches to a `Dialog` root, because a drawer is a dialog underneath. */
const createDrawerHandle = DrawerPrimitive.createHandle

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
                        <div className="mx-auto flex min-h-0 w-full max-w-[32rem] flex-col">{children}</div>
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
            className={cn('quill-drawer__footer mt-auto flex flex-col-reverse gap-2 p-4', className)}
            {...props}
        />
    )
})

const DrawerBody = React.forwardRef<
    HTMLDivElement,
    useRender.ComponentProps<'div'> & {
        /** Class for the ScrollArea viewport, the element that scrolls. Ignored when `render` is set. */
        viewportClassName?: string
    }
>(function DrawerBody({ className, render, children, viewportClassName, ...props }, ref) {
    // `useRender` runs on every render, so the default ScrollArea is a template rather than a branch.
    const effectiveRender = render ?? (
        <ScrollArea
            data-slot="drawer-body"
            className={cn('quill-drawer__body', className)}
            viewportClassName={viewportClassName}
        />
    )
    return useRender({
        ref,
        defaultTagName: 'div',
        props: mergeProps<'div'>(
            { className: cn('quill-drawer__body', className), children } as Omit<React.ComponentProps<'div'>, 'ref'>,
            props
        ),
        render: effectiveRender,
        state: { slot: 'drawer-body' },
    })
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
    DrawerBody,
    DrawerFooter,
    DrawerTitle,
    DrawerDescription,
    createDrawerHandle,
}
