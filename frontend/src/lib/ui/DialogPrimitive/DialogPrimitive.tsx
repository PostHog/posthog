import { Dialog } from '@base-ui/react/dialog'
import { Suspense } from 'react'

import { IconX } from '@posthog/icons'

import { useKeyboardInsets } from 'lib/hooks/useKeyboardInsets'
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
    useKeyboardInsets(open)

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
                            // Subtract whatever the on-screen keyboard covers, which no CSS unit sees,
                            // so the scroll pane can't end up below the fold. Both insets are 0 without
                            // a keyboard. Below `sm` the popup uses the full height rather than 60dvh —
                            // a phone has no room to spare for a compact overlay.
                            'top-[calc(1rem+var(--keyboard-inset-top))] max-h-[calc(100dvh-2rem-var(--keyboard-inset-bottom))]',
                            'sm:max-h-[calc(60dvh-var(--keyboard-inset-bottom))]',
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
