import { Dialog as DialogPrimitive } from '@base-ui/react/dialog'
import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { XIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
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
            data-slot="dialog-overlay"
            className={cn(
                'fixed inset-0 min-h-dvh bg-black opacity-20 transition-all duration-150 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0 dark:opacity-70 supports-[-webkit-touch-callout:none]:absolute',
                className
            )}
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
                data-slot="dialog-content"
                className={cn(
                    'fixed top-[calc(max(1rem,10vh+1.25rem*var(--nested-dialogs)))] start-1/2 z-50 grid w-full max-w-[calc(100vw-3rem)] -translate-x-1/2 rtl:translate-x-1/2 scale-[calc(1-0.1*var(--nested-dialogs))] gap-4 rounded-xl bg-background text-xs/relaxed ring-1 ring-foreground/10 outline-none transition-all duration-150 sm:max-w-sm',
                    'data-[starting-style]:scale-90 data-[starting-style]:opacity-0 data-[ending-style]:scale-90 data-[ending-style]:opacity-0',
                    'data-[nested-dialog-open]:after:absolute data-[nested-dialog-open]:after:inset-0 data-[nested-dialog-open]:after:rounded-[inherit] data-[nested-dialog-open]:after:bg-black/5',
                    className
                )}
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
    return <div data-slot="dialog-header" className={cn('flex flex-col gap-1 px-4 pt-4 has-[~[data-slot=dialog-body]]:pb-4 has-[~[data-slot=dialog-body]]:border-b', className)} {...props} />
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
            className={cn('bg-muted/30 px-4 py-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end border-t', className)}
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
                // If the dialog body renders as a scroll area, we need to add some negative margin to the dialog body to compensate for gap in the dialog, and then add the padding of the scroll area to the viewport
                className: cn('px-4 data-[component=scroll-area]:-my-4 data-[component=scroll-area]:[&>[data-slot=scroll-area-viewport]]:py-4', className),
            },
            props
        ),
        render,
        state: { slot: 'dialog-body' },
    })
}

function DialogTitle({ className, ...props }: DialogPrimitive.Title.Props): React.ReactElement {
    return (
        <DialogPrimitive.Title data-slot="dialog-title" className={cn('text-sm font-medium', className)} {...props} />
    )
}

function DialogDescription({ className, ...props }: DialogPrimitive.Description.Props): React.ReactElement {
    return (
        <DialogPrimitive.Description
            data-slot="dialog-description"
            className={cn(
                'text-xs/relaxed text-muted-foreground *:[a]:underline *:[a]:underline-offset-3 *:[a]:hover:text-foreground',
                className
            )}
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
