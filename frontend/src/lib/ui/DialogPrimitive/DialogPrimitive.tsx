import { Dialog } from '@base-ui/react/dialog'
import { Suspense, lazy } from 'react'

import { IconX } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { WrappingLoadingSkeleton } from '../WrappingLoadingSkeleton/WrappingLoadingSkeleton'

const ButtonPrimitive = lazy(() => import('../Button/ButtonPrimitives').then((m) => ({ default: m.ButtonPrimitive })))

function DialogPrimitive({
    children,
    open,
    onOpenChange,
    className,
}: {
    children: React.ReactNode
    open: boolean
    onOpenChange: (open: boolean, eventDetails?: Dialog.Root.ChangeEventDetails) => void
    className?: string
}): JSX.Element {
    return (
        <Dialog.Root open={open} onOpenChange={(open, event) => onOpenChange(open, event)}>
            <Dialog.Portal>
                <Dialog.Backdrop className="fixed inset-0 min-h-dvh min-w-dvw bg-black opacity-20 transition-all duration-150 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0 dark:opacity-70 z-[var(--z-modal)]" />
                <Dialog.Popup
                    className={cn(
                        '@container fixed top-4 left-1/2 w-[400px] max-w-[calc(100vw-3rem)] max-h-[60vh] -translate-x-1/2 rounded-lg bg-surface-secondary shadow-xl border border-primary transition-all duration-150 data-[ending-style]:scale-95 data-[ending-style]:opacity-0 data-[starting-style]:scale-95 data-[starting-style]:opacity-0 flex flex-col overflow-hidden z-[var(--z-force-modal-above-popovers)]',
                        className
                    )}
                >
                    {children}
                </Dialog.Popup>
            </Dialog.Portal>
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

export { DialogPrimitive, DialogPrimitiveTitle, DialogClose }
