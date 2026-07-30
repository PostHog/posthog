import { Dialog } from '@base-ui/react/dialog'
import { Suspense } from 'react'

import { IconX } from '@posthog/icons'

import { useVisualViewportBounds } from 'lib/hooks/useVisualViewportBounds'
import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { WrappingLoadingSkeleton } from '../WrappingLoadingSkeleton/WrappingLoadingSkeleton'

const ButtonPrimitive = lazyWithRetry(() =>
    import('../Button/ButtonPrimitives').then((m) => ({ default: m.ButtonPrimitive }))
)

function DialogPrimitive({
    children,
    open,
    onOpenChange,
    className,
    disablePointerDismissal = false,
}: {
    children: React.ReactNode
    open: boolean
    onOpenChange: (open: boolean, eventDetails?: Dialog.Root.ChangeEventDetails) => void
    className?: string
    disablePointerDismissal?: boolean
}): JSX.Element {
    useVisualViewportBounds(open)

    return (
        <Dialog.Root
            open={open}
            onOpenChange={(open, event) => onOpenChange(open, event)}
            disablePointerDismissal={disablePointerDismissal}
        >
            {open && (
                <Dialog.Portal>
                    <Dialog.Backdrop className="fixed inset-0 min-h-dvh min-w-dvw bg-black opacity-20 transition-all duration-150 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0 dark:opacity-70 z-[var(--z-modal)]" />
                    <Dialog.Popup
                        className={cn(
                            '@container fixed left-1/2 w-[400px] max-w-[calc(100vw-2rem)] -translate-x-1/2 rounded-lg bg-surface-secondary shadow-xl border border-primary transition-all duration-150 data-[ending-style]:scale-95 data-[ending-style]:opacity-0 data-[starting-style]:scale-95 data-[starting-style]:opacity-0 flex flex-col min-h-0 overflow-hidden overscroll-contain z-[var(--z-force-modal-above-popovers)]',
                            // Sized and positioned against the visible viewport, not the layout one: on
                            // mobile the latter reaches behind the browser chrome and the on-screen
                            // keyboard, which would push the scroll pane below the fold. Above `sm` the
                            // popup stays a compact overlay rather than filling the window.
                            'top-[calc(var(--visual-viewport-offset-top)+1rem)] max-h-[calc(var(--visual-viewport-height)-2rem)]',
                            'sm:max-h-[min(60dvh,calc(var(--visual-viewport-height)-2rem))]',
                            className
                        )}
                    >
                        {children}
                    </Dialog.Popup>
                </Dialog.Portal>
            )}
        </Dialog.Root>
    )
}

function DialogPrimitiveTitle({
    children,
    className = 'sr-only',
}: {
    children: React.ReactNode
    className?: string
}): JSX.Element {
    return <Dialog.Title className={className}>{children}</Dialog.Title>
}

function DialogClose({ className = '' }: { className?: string }): JSX.Element {
    return (
        <Suspense
            fallback={
                <WrappingLoadingSkeleton className={cn('size-[30px]', className)}>
                    <IconX />
                </WrappingLoadingSkeleton>
            }
        >
            <Dialog.Close
                className={className}
                render={
                    <ButtonPrimitive iconOnly>
                        <IconX />
                    </ButtonPrimitive>
                }
            />
        </Suspense>
    )
}

function DialogTrigger({ children, ...rest }: React.ComponentProps<typeof Dialog.Trigger>): JSX.Element {
    return <Dialog.Trigger {...rest}>{children}</Dialog.Trigger>
}

export { DialogPrimitive, DialogPrimitiveTitle, DialogClose, DialogTrigger }
