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

function AlertDialogTrigger({ ...props }: AlertDialogPrimitive.Trigger.Props): React.ReactElement {
    return <AlertDialogPrimitive.Trigger data-slot="alert-dialog-trigger" {...props} />
}

function AlertDialogPortal({ ...props }: AlertDialogPrimitive.Portal.Props): React.ReactElement {
    return <AlertDialogPrimitive.Portal data-slot="alert-dialog-portal" {...props} />
}

function AlertDialogClose({ ...props }: AlertDialogPrimitive.Close.Props): React.ReactElement {
    return <AlertDialogPrimitive.Close data-slot="alert-dialog-close" {...props} />
}

function AlertDialogOverlay({ className, ...props }: AlertDialogPrimitive.Backdrop.Props): React.ReactElement {
    return (
        <AlertDialogPrimitive.Backdrop
            data-quill
            data-quill-portal="modal-overlay"
            data-slot="alert-dialog-overlay"
            className={cn('quill-dialog__overlay', className)}
            {...props}
        />
    )
}

/*
 * Unlike DialogContent there is deliberately no `showCloseButton` — an alert
 * dialog must be resolved through one of its actions (or Esc), so an X would
 * just be an ambiguous third option.
 */
function AlertDialogContent({ className, children, ...props }: AlertDialogPrimitive.Popup.Props): React.ReactElement {
    return (
        <AlertDialogPortal>
            <AlertDialogOverlay />
            <AlertDialogPrimitive.Popup
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
}

function AlertDialogTitle({ className, ...props }: AlertDialogPrimitive.Title.Props): React.ReactElement {
    return (
        <AlertDialogPrimitive.Title
            data-slot="alert-dialog-title"
            className={cn('quill-dialog__title', className)}
            {...props}
        />
    )
}

function AlertDialogDescription({ className, ...props }: AlertDialogPrimitive.Description.Props): React.ReactElement {
    return (
        <AlertDialogPrimitive.Description
            data-slot="alert-dialog-description"
            className={cn('quill-dialog__description', className)}
            {...props}
        />
    )
}

function AlertDialogHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="alert-dialog-header"
            className={cn('quill-dialog__header flex flex-col gap-1', className)}
            {...props}
        />
    )
}

function AlertDialogFooter({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="alert-dialog-footer"
            className={cn('quill-dialog__footer flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)}
            {...props}
        />
    )
}

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
