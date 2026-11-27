import posthog from 'posthog-js'
import { useRef } from 'react'
import { toast, type ToastOptions, type UpdateOptions } from 'react-toastify'

import { IconCheckCircle, IconCopy, IconInfo, IconWarning, IconX } from '@posthog/icons'

import { isChristmas } from 'lib/utils/holidays'
import { hashCodeForString } from 'lib/utils/strings'
import { writeToClipboard } from 'lib/utils/writeToClipboard'

import { IconErrorOutline, IconGift } from '../icons'
import { LemonButton } from '../LemonButton'
import { Spinner } from '../Spinner'
import { getHelp } from './getHelp'
import { quillToastBackend, quillToastsMounted } from './quillToast'
import {
    type ToastBackend,
    type ToastError,
    type ToastKind,
    type ToastPromiseMessages,
    type ToastSpec,
    promiseSuccessMessage,
} from './toastBackend'
import { incidentNote, withClickableUrls } from './toastMessage'

export function ToastCloseButton({
    closeToast,
}: {
    closeToast?: (event: React.MouseEvent<HTMLElement>) => void
}): JSX.Element {
    return (
        <LemonButton
            type="tertiary"
            size="small"
            icon={<IconX />}
            onClick={closeToast}
            data-attr="toast-close-button"
        />
    )
}

export interface ToastButton {
    label: string
    action: (() => void) | (() => Promise<void>)
    dataAttr?: string
    className?: string
}

export interface ToastOptionsWithButton<T = string> extends ToastOptions<T> {
    button?: ToastButton
    hideButton?: boolean
    /** Runs when the user closes the toast, not when it times out. */
    onDismiss?: () => void
}

interface ErrorToastOptions<T = string> extends ToastOptionsWithButton<T> {
    /** Sent to analytics in place of `message`, for a message that can repeat text the user typed. */
    capturedMessage?: string
}

interface SuccessToastOptions<T = string> extends ToastOptionsWithButton<T> {
    /** A second action, shown after `button` on a row under the message. */
    secondaryButton?: ToastButton
}

export const GET_HELP_BUTTON: ToastButton = {
    label: 'Get help',
    action: getHelp,
}

// Fallback for when submitting a support ticket in-app fails: let the user reach us
// directly by email instead of being sent back to the form that just failed.
export const EMAIL_SUPPORT_BUTTON: ToastButton = {
    label: 'Email us directly',
    action: () => {
        window.location.href = 'mailto:supportreply@posthog.com?subject=PostHog support request'
    },
}

const successIcon = (): JSX.Element => (isChristmas() ? <IconGift className="text-green-600" /> : <IconCheckCircle />)

export interface ToastContentProps {
    type: 'info' | 'success' | 'warning' | 'error'
    message: string | JSX.Element
    button?: ToastButton
    secondaryButton?: ToastButton
    id?: number | string
}

export function ToastActionButton({
    button,
    toastId,
}: {
    button: ToastButton
    toastId?: number | string
}): JSX.Element {
    return (
        <LemonButton
            onClick={() => {
                void button.action()
                lemonToast.dismiss(toastId)
            }}
            type="secondary"
            size="small"
            data-attr={button.dataAttr}
            className={button.className}
        >
            {button.label}
        </LemonButton>
    )
}

/**
 * The outcome is reported here rather than through `lib/utils/copyToClipboard`, which would make this
 * module and that one require each other. Both sides share the clipboard mechanics through
 * `writeToClipboard`, so the plain-HTTP fallback the toolbar depends on stays in one place.
 *
 * The notice is an info toast because an error or warning would carry a copy button of its own, and
 * clicking it would fail the same way.
 */
async function copyMessage(text: string): Promise<void> {
    const outcome = await writeToClipboard(text)
    if (outcome === 'copied') {
        lemonToast.info('Copied message to clipboard', { icon: <IconCopy /> })
        return
    }
    lemonToast.info('Could not reach the clipboard. Select the message and copy it manually.')
}

function ToastCopyButton({ getMessageText }: { getMessageText: () => string }): JSX.Element {
    return (
        <LemonButton
            type="tertiary"
            size="small"
            noPadding
            // `.Toastify__toast-body button` sets a 0.75rem side margin sized for the action button,
            // which costs the message a line of wrapping at the toast's fixed 26rem width.
            className="shrink-0 !mx-2"
            icon={<IconCopy />}
            tooltip="Copy message"
            onClick={() => void copyMessage(getMessageText())}
            data-attr="toast-copy-button"
        />
    )
}

export function ToastContent({ type, message, button, secondaryButton, id }: ToastContentProps): JSX.Element {
    const messageRef = useRef<HTMLSpanElement>(null)

    if (secondaryButton) {
        // Two actions leave the message no room on one line, so they go on a row under it.
        return (
            <div className="flex flex-col gap-2" data-attr={`${type}-toast`}>
                <span>{message}</span>
                <div className="flex gap-2 [&_button]:!mx-0">
                    {button && <ToastActionButton button={button} toastId={id} />}
                    <ToastActionButton button={secondaryButton} toastId={id} />
                </div>
            </div>
        )
    }

    return (
        <div className="flex items-center" data-attr={`${type}-toast`}>
            <span ref={messageRef} className="grow min-w-0 overflow-hidden text-ellipsis">
                {message}
            </span>
            {/* Only on the types whose text people take elsewhere, so confirmations keep their full width. */}
            {(type === 'error' || type === 'warning') && (
                // innerText breaks at block boundaries, so a message that renders the incident note under
                // itself copies as two lines. textContent would run them together, and is the fallback
                // only because jsdom does not implement innerText.
                <ToastCopyButton
                    getMessageText={() => messageRef.current?.innerText ?? messageRef.current?.textContent ?? ''}
                />
            )}
            {button && <ToastActionButton button={button} toastId={id} />}
        </div>
    )
}

function ensureToastId<O extends ToastOptions<any>>(toastOptions: O, type: string, message?: string | JSX.Element): O {
    if (toastOptions.toastId) {
        return toastOptions
    }
    // Use a deterministic ID based on type + message so that react-toastify
    // will skip showing a duplicate toast if one with the same type and message is already visible.
    const toastId =
        typeof message === 'string'
            ? `lemon-${type}-${hashCodeForString(message)}`
            : `lemon-${Math.round(Math.random() * 10000000)}`
    return { ...toastOptions, toastId }
}

function withIncidentNote(message: string | JSX.Element): string | JSX.Element {
    const note = incidentNote('block text-xs mt-1 opacity-75')
    if (!note) {
        return message
    }

    return (
        <>
            <span className="block">{message}</span>
            {note}
        </>
    )
}

function toastifyOptions<T>({ onDismiss, ...options }: ToastOptionsWithButton<T>): ToastOptions<T> {
    if (!onDismiss) {
        return options
    }
    return {
        ...options,
        closeButton: ({ closeToast }) => (
            <ToastCloseButton
                closeToast={(event) => {
                    closeToast(event)
                    onDismiss()
                }}
            />
        ),
    }
}

const toastifyIcons: Record<ToastKind, () => JSX.Element> = {
    info: () => <IconInfo />,
    loading: () => <Spinner />,
    success: successIcon,
    warning: () => <IconWarning />,
    error: () => <IconErrorOutline />,
}

function toastifyContent({ kind, id, message, button, secondaryButton }: Omit<ToastSpec, 'options'>): JSX.Element {
    return (
        <ToastContent
            type={kind === 'loading' ? 'info' : kind}
            message={kind === 'error' ? withIncidentNote(withClickableUrls(message)) : message}
            button={button}
            secondaryButton={secondaryButton}
            id={id}
        />
    )
}

// Each toast waits a microtask so React can flush the re-render with the updated theme on ToastContainer.
// A dismiss that lands in that gap cancels it.
const pendingIds = new Set<number | string>()
const cancelledIds = new Set<number | string>()

const toastifyBackend: ToastBackend = {
    show(spec) {
        pendingIds.add(spec.id)
        queueMicrotask(() => {
            pendingIds.delete(spec.id)
            if (!cancelledIds.delete(spec.id)) {
                toast[spec.kind](toastifyContent(spec), {
                    icon: toastifyIcons[spec.kind](),
                    ...toastifyOptions(spec.options),
                })
            }
        })
    },
    showSuccessInPlace({ options, ...spec }) {
        toast.update(spec.id, {
            render: toastifyContent({ ...spec, kind: 'success' }),
            type: 'success',
            icon: successIcon(),
            // react-toastify drops null props so the container's defaults apply again. This is the
            // same reset its own promise() resolver does when leaving the loading state.
            isLoading: null,
            autoClose: null,
            closeOnClick: null,
            closeButton: null,
            draggable: null,
            ...options,
        } as UpdateOptions)
    },
    promise(promise, messages, spec) {
        // see https://fkhadra.github.io/react-toastify/promise
        return toast.promise<string | undefined, ToastError>(
            promise,
            {
                pending: {
                    render: toastifyContent({ ...spec, kind: 'loading', message: messages.pending }),
                    icon: toastifyIcons.loading(),
                },
                success: {
                    render: ({ data }) =>
                        toastifyContent({ ...spec, kind: 'success', message: promiseSuccessMessage(messages, data) }),
                    icon: toastifyIcons.success(),
                },
                error: {
                    render: ({ data }) =>
                        toastifyContent({ ...spec, kind: 'error', message: data?.message || messages.error }),
                    icon: toastifyIcons.error(),
                },
            },
            spec.options
        )
    },
    isActive: (id) => toast.isActive(id),
    keepOpen: (id) => toast.update(id, { autoClose: false }),
    dismiss(id) {
        if (id !== undefined && pendingIds.has(id)) {
            cancelledIds.add(id)
        }
        toast.dismiss(id)
    },
}

function backend(): ToastBackend {
    return quillToastsMounted() ? quillToastBackend : toastifyBackend
}

function show(
    kind: ToastKind,
    message: string | JSX.Element,
    { button, secondaryButton, ...toastOptions }: SuccessToastOptions
): number | string {
    const options = ensureToastId(toastOptions, kind, message)
    const id = options.toastId!
    backend().show({ kind, id, message, button, secondaryButton, options })
    return id
}

/** The toolbar bundle initializes a named posthog-js instance, so this default one stays unloaded there. */
function captureToast(event: string, message: string, button: ToastButton | undefined, toastId: unknown): void {
    if (posthog.__loaded) {
        posthog.capture(event, { message, button: button?.label, toastId })
    }
}

export const lemonToast = {
    info(message: string | JSX.Element, options: ToastOptionsWithButton = {}) {
        return show('info', message, options)
    },
    loading(message: string | JSX.Element, options: ToastOptionsWithButton = {}) {
        return show('loading', message, options)
    },
    success(message: string | JSX.Element, options: SuccessToastOptions = {}) {
        return show('success', message, options)
    },
    warning(message: string | JSX.Element, options: ToastOptionsWithButton = {}) {
        captureToast('toast warning', String(message), options.button, options.toastId)
        return show('warning', message, options)
    },
    error(message: string | JSX.Element, { button, hideButton, capturedMessage, ...options }: ErrorToastOptions = {}) {
        captureToast('toast error', capturedMessage ?? String(message), button, options.toastId)
        return show('error', message, {
            ...options,
            button: button !== undefined ? button : hideButton ? undefined : GET_HELP_BUTTON,
        })
    },
    promise(
        promise: Promise<any>,
        messages: ToastPromiseMessages,
        { button, ...toastOptions }: ToastOptionsWithButton = {}
    ): Promise<any> {
        const options = ensureToastId(toastOptions, 'promise')
        return backend().promise(promise, messages, { id: options.toastId!, button, options })
    },
    updateToSuccess(
        id: number | string,
        message: string | JSX.Element,
        { button, ...options }: ToastOptionsWithButton = {}
    ): void {
        backend().showSuccessInPlace({ id, message, button, options: { ...options, toastId: id } })
    },
    isActive(id: number | string): boolean {
        return backend().isActive(id)
    },
    /** Stops the toast's auto-dismiss timer, for when the user is busy with something it opened. */
    keepOpen(id: number | string): void {
        backend().keepOpen(id)
    },
    dismiss(id?: number | string): void {
        backend().dismiss(id)
    },
}
