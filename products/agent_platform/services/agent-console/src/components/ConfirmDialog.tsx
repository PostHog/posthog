/**
 * `<ConfirmDialog />` — small wrapper over Quill's Dialog primitive
 * for one-shot confirms (promote, archive, etc).
 *
 * Controlled by parent: `open` + `onOpenChange`. The action button
 * is disabled while `running` so a slow upstream can't be double-
 * fired. An `error` string is rendered inline so the user can decide
 * whether to retry without dismissing the dialog.
 */

'use client'

import {
    Button,
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@posthog/quill'

export interface ConfirmDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    title: string
    description: React.ReactNode
    confirmLabel: string
    /** Visual treatment for the action button. Default = `default`. */
    confirmVariant?: 'default' | 'destructive'
    running?: boolean
    error?: string | null
    onConfirm: () => void
}

export function ConfirmDialog({
    open,
    onOpenChange,
    title,
    description,
    confirmLabel,
    confirmVariant = 'default',
    running,
    error,
    onConfirm,
}: ConfirmDialogProps): React.ReactElement {
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                    <DialogDescription>{description}</DialogDescription>
                </DialogHeader>
                {error ? <div className="text-sm text-destructive-foreground">{error}</div> : null}
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                    <Button
                        variant={confirmVariant}
                        onClick={onConfirm}
                        disabled={running}
                        aria-busy={running ? 'true' : undefined}
                    >
                        {running ? 'Working…' : confirmLabel}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
