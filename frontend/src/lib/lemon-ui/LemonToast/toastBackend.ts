import type { ToastButton, ToastOptionsWithButton } from './LemonToast'

export type ToastKind = 'info' | 'success' | 'warning' | 'error' | 'loading'

export interface ToastSpec {
    kind: ToastKind
    id: number | string
    message: string | JSX.Element
    button?: ToastButton
    secondaryButton?: ToastButton
    options: ToastOptionsWithButton
}

export interface ToastPromiseMessages {
    pending: string | JSX.Element
    /** A function is called when the promise settles, so it can read state that changed while it ran. */
    success: string | JSX.Element | ((data?: string) => string | JSX.Element)
    error: string | JSX.Element
}

export interface ToastError {
    message: string
}

/** Renders lemonToast's toasts. lemonToast resolves ids, defaults and analytics before it calls one. */
export interface ToastBackend {
    show(spec: ToastSpec): void
    /** Turns the toast with this id into a success toast, or shows one when it is gone. */
    showSuccessInPlace(spec: Omit<ToastSpec, 'kind'>): void
    promise(
        promise: Promise<any>,
        messages: ToastPromiseMessages,
        spec: Omit<ToastSpec, 'kind' | 'message'>
    ): Promise<any>
    isActive(id: number | string): boolean
    keepOpen(id: number | string): void
    dismiss(id?: number | string): void
}

export function promiseSuccessMessage(messages: ToastPromiseMessages, data: string | undefined): string | JSX.Element {
    return typeof messages.success === 'function' ? messages.success(data) : data || messages.success
}
