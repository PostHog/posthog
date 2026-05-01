import { Dialog as DialogPrimitive } from '@base-ui/react/dialog'
import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { XIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import './dialog.css'
import { cn } from './lib/utils'

/** Note: if you're nesting dialogs, in order for you to click the overlay to close it, you must pass 'mounted: true' to the nested dialog*/
function Dialog({ ...props }: DialogPrimitive.Root.Props): React.ReactElement {
    return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

function DialogTrigger({ ...props }: DialogPrimitive.Trigger.Props): React.ReactElement {
    return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />
}

function DialogPortal({ ...props }: DialogPrimitive.Portal.Props): React.ReactElement {
    return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />
}

function DialogClose({ ...props }: DialogPrimitive.Close.Props): React.ReactElement {
    return <DialogPrimitive.Close data-slot="dialog-close" {...props} />
}

function DialogOverlay({ className, ...props }: DialogPrimitive.Backdrop.Props): React.ReactElement {
    return (
        <DialogPrimitive.Backdrop
            data-quill
            data-quill-portal="modal-overlay"
            data-slot="dialog-overlay"
            className={cn('quill-dialog__overlay', className)}
            {...props}
        />
    )
}

function DialogContent({
    className,
    children,
    showCloseButton = true,
    nested = false,
    ...props
}: DialogPrimitive.Popup.Props & {
    showCloseButton?: boolean
    nested?: boolean
}): React.ReactElement {
    return (
        <DialogPortal>
            <DialogOverlay />
            <DialogPrimitive.Popup
                data-quill
                data-quill-portal="modal-content"
                data-slot="dialog-content"
                className={cn('quill-dialog__content grid gap-4', className)}
                {...props}
            >
                {children}
                {showCloseButton && (
                    <DialogPrimitive.Close
                        data-slot="dialog-close"
                        render={<Button className="absolute top-2 end-2" size="icon-sm" />}
                    >
                        <XIcon />
                        <span className="sr-only">Close</span>
                    </DialogPrimitive.Close>
                )}
            </DialogPrimitive.Popup>
        </DialogPortal>
    )
}

function DialogHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="dialog-header" className={cn('quill-dialog__header flex flex-col gap-1', className)} {...props} />
}

function DialogFooter({
    className,
    showCloseButton = false,
    children,
    ...props
}: React.ComponentProps<'div'> & {
    showCloseButton?: boolean
}): React.ReactElement {
    return (
        <div
            data-slot="dialog-footer"
            className={cn('quill-dialog__footer flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)}
            {...props}
        >
            {children}
            {showCloseButton && (
                <DialogPrimitive.Close render={<Button variant="outline" />}>Close</DialogPrimitive.Close>
            )}
        </div>
    )
}

function DialogBody({ className, render, ...props }: useRender.ComponentProps<'div'>): React.ReactElement {
    return useRender({
        defaultTagName: 'div',
        props: mergeProps<'div'>(
            {
                className: cn('quill-dialog__body', className),
            } as Omit<React.ComponentProps<'div'>, 'ref'>,
            props
        ),
        render,
        state: { slot: 'dialog-body' },
    })
}

function DialogTitle({ className, ...props }: DialogPrimitive.Title.Props): React.ReactElement {
    return <DialogPrimitive.Title data-slot="dialog-title" className={cn('quill-dialog__title', className)} {...props} />
}

function DialogDescription({ className, ...props }: DialogPrimitive.Description.Props): React.ReactElement {
    return (
        <DialogPrimitive.Description
            data-slot="dialog-description"
            className={cn('quill-dialog__description', className)}
            {...props}
        />
    )
}

export {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogBody,
    DialogOverlay,
    DialogPortal,
    DialogTitle,
    DialogTrigger,
}
