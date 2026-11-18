import posthog from 'posthog-js'
import { type ReactNode, useState } from 'react'
import { createRoot } from 'react-dom/client'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export interface QuillConfirmOptions {
    title: string
    description: ReactNode
    confirmLabel: string
    destructive?: boolean
    cancelLabel?: string
    dataAttr?: string
    onConfirm: () => void | Promise<void>
    awaitConfirm?: boolean
}

function captureUnexpectedConfirmError(error: unknown): void {
    if (!(error instanceof ApiError) || (error.status ?? 500) >= 500) {
        posthog.captureException(error)
    }
}

function MountedQuillConfirm({
    options,
    onClosed,
}: {
    options: QuillConfirmOptions
    onClosed: () => void
}): JSX.Element {
    const {
        title,
        description,
        confirmLabel,
        destructive = false,
        cancelLabel = 'Cancel',
        dataAttr,
        onConfirm,
        awaitConfirm = false,
    } = options
    const [open, setOpen] = useState(true)
    const [loading, setLoading] = useState(false)
    const confirmVariant = destructive ? 'destructive' : 'primary'

    const confirm = async (): Promise<void> => {
        setLoading(true)
        try {
            await onConfirm()
        } catch (error) {
            captureUnexpectedConfirmError(error)
            return
        } finally {
            setLoading(false)
        }
        setOpen(false)
    }

    return (
        <AlertDialog
            open={open}
            onOpenChange={(next: boolean) => !loading && setOpen(next)}
            onOpenChangeComplete={(next: boolean) => !next && onClosed()}
        >
            <AlertDialogContent data-attr={dataAttr}>
                <AlertDialogHeader>
                    <AlertDialogTitle>{title}</AlertDialogTitle>
                    <AlertDialogDescription render={<div />}>{description}</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose
                        render={<Button variant="outline" disabledReason={loading ? 'Please wait...' : undefined} />}
                    >
                        {cancelLabel}
                    </AlertDialogClose>
                    {awaitConfirm ? (
                        <Button variant={confirmVariant} loading={loading} onClick={() => void confirm()}>
                            {confirmLabel}
                        </Button>
                    ) : (
                        <AlertDialogClose render={<Button variant={confirmVariant} onClick={() => void onConfirm()} />}>
                            {confirmLabel}
                        </AlertDialogClose>
                    )}
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}

export function openQuillConfirm(options: QuillConfirmOptions): void {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    const destroy = (): void => {
        setTimeout(() => {
            root.unmount()
            container.remove()
        }, 0)
    }
    root.render(<MountedQuillConfirm options={options} onClosed={destroy} />)
}

export function isQuillExperimentsView(): boolean {
    const featureFlags = featureFlagLogic.findMounted()?.values.featureFlags
    return (
        !!featureFlags?.[FEATURE_FLAGS.TODAY_RAIL_NAV] && !!featureFlags?.[FEATURE_FLAGS.EXPERIMENTS_RESULTS_REDESIGN]
    )
}
