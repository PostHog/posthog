import type { ToastAction, ToastOptions, toast as quillToast } from '@posthog/quill'

import type { ToastButton } from './LemonToast'
import { type ToastBackend, type ToastError, type ToastSpec, promiseSuccessMessage } from './toastBackend'
import { incidentNote, withClickableUrls } from './toastMessage'

/** How long a toast with an action stays up, so there is time to read it and click. */
export const ACTION_TOAST_TIMEOUT_MS = 8000

interface ActiveToast {
    quillId: string
    options: ToastOptions
}

// Handed in by the app shell that mounts quill's viewport, so bundles without one never load quill.
let toast: typeof quillToast | null = null
// Keyed by the lemonToast id, so a repeat id updates its toast instead of stacking a second one.
const activeToasts = new Map<string, ActiveToast>()

export function setQuillToasts(api: typeof quillToast | null): void {
    toast = api
    activeToasts.clear()
}

export function quillToastsMounted(): boolean {
    return toast !== null
}

function quill(): typeof quillToast {
    if (!toast) {
        throw new Error('Quill toasts are not mounted')
    }
    return toast
}

function toAction(button: ToastButton | undefined): ToastAction | undefined {
    return button && { label: button.label, onClick: () => void button.action() }
}

function timeout({ kind, button, secondaryButton, options }: ToastSpec): number | undefined {
    if (kind === 'loading' || options.autoClose === false) {
        return 0
    }
    return options.autoClose ?? (button || secondaryButton ? ACTION_TOAST_TIMEOUT_MS : undefined)
}

function show(spec: ToastSpec): void {
    const id = String(spec.id)
    const { kind, options } = spec
    const error = kind === 'error'
    const quillOptions: ToastOptions = {
        type: options.icon === false ? undefined : kind,
        title: (
            <span data-attr={`${kind === 'loading' ? 'info' : kind}-toast`}>
                {error ? withClickableUrls(spec.message) : spec.message}
            </span>
        ),
        description: error ? incidentNote() : undefined,
        timeout: timeout(spec),
        action: toAction(spec.button),
        secondaryAction: toAction(spec.secondaryButton),
        onDismiss: options.onDismiss,
        onClose: () => {
            if (activeToasts.get(id)?.quillId === quillId) {
                activeToasts.delete(id)
            }
            options.onClose?.(undefined)
        },
    }
    const existing = activeToasts.get(id)
    const quillId = existing ? existing.quillId : quill()(quillOptions)
    if (existing) {
        quill().update(quillId, quillOptions)
    }
    activeToasts.set(id, { quillId, options: quillOptions })
}

export const quillToastBackend: ToastBackend = {
    show,
    showSuccessInPlace: (spec) => show({ ...spec, kind: 'success' }),
    promise(promise, messages, spec) {
        show({ ...spec, kind: 'loading', message: messages.pending })
        promise.then(
            (data) => show({ ...spec, kind: 'success', message: promiseSuccessMessage(messages, data) }),
            (error: ToastError | undefined) =>
                show({ ...spec, kind: 'error', message: error?.message || messages.error })
        )
        return promise
    },
    isActive: (id) => activeToasts.has(String(id)),
    keepOpen(id) {
        const active = activeToasts.get(String(id))
        if (active) {
            active.options = { ...active.options, timeout: 0 }
            quill().update(active.quillId, active.options)
        }
    },
    dismiss(id) {
        if (id === undefined) {
            activeToasts.clear()
            quill().dismiss()
            return
        }
        const active = activeToasts.get(String(id))
        if (active) {
            activeToasts.delete(String(id))
            quill().dismiss(active.quillId)
        }
    },
}
