import { useSyncExternalStore } from 'react'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

interface Ask {
    title: string
    body?: string
    confirm?: string
    destructive?: boolean
}

let current: (Ask & { resolve: (ok: boolean) => void }) | undefined
const listeners = new Set<() => void>()
const emit = (): void => listeners.forEach((listener) => listener())
const subscribe = (listener: () => void): (() => void) => {
    listeners.add(listener)
    return () => listeners.delete(listener)
}

export function confirmDialog(ask: Ask): Promise<boolean> {
    current?.resolve(false)
    return new Promise((resolve) => {
        current = { ...ask, resolve }
        emit()
    })
}

export function ConfirmHost(): JSX.Element {
    const ask = useSyncExternalStore(subscribe, () => current)
    const close = (ok: boolean): void => {
        const asked = current
        current = undefined
        emit()
        asked?.resolve(ok)
    }
    return (
        <AlertDialog open={!!ask} onOpenChange={(open: boolean) => !open && close(false)}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{ask?.title}</AlertDialogTitle>
                    {ask?.body && <AlertDialogDescription>{ask.body}</AlertDialogDescription>}
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button variant="outline" onClick={() => close(false)}>
                        Cancel
                    </Button>
                    <Button
                        variant={ask?.destructive === false ? 'primary' : 'destructive-outline'}
                        onClick={() => close(true)}
                        data-attr="dashboard-v2-confirm"
                    >
                        {ask?.confirm ?? 'Delete'}
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
