import './dialog.css'

import { AlertDialog as AlertDialogPrimitive } from '@base-ui/react/alert-dialog'
import * as React from 'react'

import { cn } from './lib/utils'

/*
 * Standalone on purpose, not a Dialog variant: Base UI's AlertDialogRoot
 * hard-codes `role="alertdialog"`, `modal: true`, and
 * `disablePointerDismissal: true` in its store — the user must make an
 * explicit choice; clicking the backdrop never closes it. Exposing those as
 * Dialog props would let consumers break the a11y contract. The visual layer
 * is fully shared: every part reuses the `quill-dialog__*` styles from
 * dialog.css.
 */
function AlertDialog({ ...props }: AlertDialogPrimitive.Root.Props): React.ReactElement {
    return <AlertDialogPrimitive.Root data-slot="alert-dialog" {...props} />
}

const AlertDialogTrigger = React.forwardRef<
    React.ComponentRef<typeof AlertDialogPrimitive.Trigger>,
    AlertDialogPrimitive.Trigger.Props
>(function AlertDialogTrigger({ ...props }, ref) {
    return <AlertDialogPrimitive.Trigger ref={ref} data-slot="alert-dialog-trigger" {...props} />
})

function AlertDialogPortal({ ...props }: AlertDialogPrimitive.Portal.Props): React.ReactElement {
    return <AlertDialogPrimitive.Portal data-slot="alert-dialog-portal" {...props} />
}

const AlertDialogClose = React.forwardRef<
    React.ComponentRef<typeof AlertDialogPrimitive.Close>,
    AlertDialogPrimitive.Close.Props
>(function AlertDialogClose({ ...props }, ref) {
    return <AlertDialogPrimitive.Close ref={ref} data-slot="alert-dialog-close" {...props} />
})

const AlertDialogOverlay = React.forwardRef<
    React.ComponentRef<typeof AlertDialogPrimitive.Backdrop>,
    AlertDialogPrimitive.Backdrop.Props
>(function AlertDialogOverlay({ className, ...props }, ref) {
    return (
        <AlertDialogPrimitive.Backdrop
            ref={ref}
            data-quill
            data-quill-portal="modal-overlay"
            data-slot="alert-dialog-overlay"
            className={cn('quill-dialog__overlay', className)}
            {...props}
        />
    )
})

/*
 * Unlike DialogContent there is deliberately no `showCloseButton` — an alert
 * dialog must be resolved through one of its actions (or Esc), so an X would
 * just be an ambiguous third option.
 */
const AlertDialogContent = React.forwardRef<
    React.ComponentRef<typeof AlertDialogPrimitive.Popup>,
    AlertDialogPrimitive.Popup.Props
>(function AlertDialogContent({ className, children, ...props }, ref) {
    return (
        <AlertDialogPortal>
            <AlertDialogOverlay />
            <AlertDialogPrimitive.Popup
                ref={ref}
                data-quill
                data-quill-portal="modal-content"
                data-slot="alert-dialog-content"
                className={cn('quill-dialog__content', className)}
                {...props}
            >
                {children}
            </AlertDialogPrimitive.Popup>
        </AlertDialogPortal>
    )
})

const AlertDialogTitle = React.forwardRef<
    React.ComponentRef<typeof AlertDialogPrimitive.Title>,
    AlertDialogPrimitive.Title.Props
>(function AlertDialogTitle({ className, ...props }, ref) {
    return (
        <AlertDialogPrimitive.Title
            ref={ref}
            data-slot="alert-dialog-title"
            className={cn('quill-dialog__title', className)}
            {...props}
        />
    )
})

const AlertDialogDescription = React.forwardRef<
    React.ComponentRef<typeof AlertDialogPrimitive.Description>,
    AlertDialogPrimitive.Description.Props
>(function AlertDialogDescription({ className, ...props }, ref) {
    return (
        <AlertDialogPrimitive.Description
            ref={ref}
            data-slot="alert-dialog-description"
            className={cn('quill-dialog__description', className)}
            {...props}
        />
    )
})

const AlertDialogHeader = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function AlertDialogHeader(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="alert-dialog-header"
            className={cn('quill-dialog__header flex flex-col gap-1', className)}
            {...props}
        />
    )
})

const AlertDialogFooter = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function AlertDialogFooter(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="alert-dialog-footer"
            className={cn('quill-dialog__footer flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)}
            {...props}
        />
    )
})

export {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogOverlay,
    AlertDialogPortal,
    AlertDialogTitle,
    AlertDialogTrigger,
}
