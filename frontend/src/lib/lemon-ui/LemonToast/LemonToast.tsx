import posthog from 'posthog-js'
import { toast, type ToastOptions, type UpdateOptions } from 'react-toastify'

import { IconCheckCircle, IconInfo, IconWarning, IconX } from '@posthog/icons'

import { getIncidentStatus, STATUS_PAGE_BASE } from 'lib/components/HelpMenu/incidentStatus'
import { isChristmas } from 'lib/holidays'
import { hashCodeForString } from 'lib/utils/strings'

import { IconErrorOutline, IconGift } from '../icons'
import { LemonButton } from '../LemonButton'
import { Link } from '../Link'
import { Spinner } from '../Spinner'

export function ToastCloseButton({ closeToast }: { closeToast?: () => void }): JSX.Element {
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

interface ToastOptionsWithButton<T = string> extends ToastOptions<T> {
    button?: ToastButton
    hideButton?: boolean
}

export const GET_HELP_BUTTON: ToastButton = {
    label: 'Get help',
    action: () => {
        window.open('https://posthog.com/support?utm_medium=in-product&utm_campaign=error-toast', '_blank')
    },
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
                // Not lemonToast.dismiss: that marks the id cancelled so the next toast reusing it
                // is swallowed, and ids are a hash of the message, so the same error would go quiet.
                toast.dismiss(toastId)
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

export function ToastContent({ type, message, button, id }: ToastContentProps): JSX.Element {
    return (
        <div className="flex items-center" data-attr={`${type}-toast`}>
            <span className="grow overflow-hidden text-ellipsis">{message}</span>
            {button && <ToastActionButton button={button} toastId={id} />}
        </div>
    )
}

function ensureToastId<T>(
    toastOptions: ToastOptions<T>,
    type: string,
    message?: string | JSX.Element
): ToastOptions<T> {
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
    const status = getIncidentStatus()
    if (status === 'operational') {
        return message
    }

    return (
        <>
            <span className="block">{message}</span>
            <Link className="block text-xs mt-1 opacity-75" to={STATUS_PAGE_BASE} target="_blank">
                There is an ongoing incident that may be related.
            </Link>
        </>
    )
}

interface ToastError {
    message: string
}

// IDs dismissed before the deferred microtask has fired. Prevents a toast from
// appearing if dismiss() is called synchronously after creation in the same tick.
const cancelledIds = new Set<number | string>()

export const lemonToast = {
    info(message: string | JSX.Element, { button, ...toastOptions }: ToastOptionsWithButton = {}) {
        const options = ensureToastId(toastOptions, 'info', message)
        const id = options.toastId!
        // Defer so React can flush the re-render with the updated theme on ToastContainer
        queueMicrotask(() => {
            if (cancelledIds.delete(id)) {
                return
            }
            toast.info(<ToastContent type="info" message={message} button={button} id={id} />, {
                icon: <IconInfo />,
                ...options,
            })
        })
        return id
    },
    loading(message: string | JSX.Element, { button, ...toastOptions }: ToastOptionsWithButton = {}) {
        const options = ensureToastId(toastOptions, 'loading', message)
        const id = options.toastId!
        queueMicrotask(() => {
            if (cancelledIds.delete(id)) {
                return
            }
            toast.loading(<ToastContent type="info" message={message} button={button} id={id} />, {
                icon: <Spinner />,
                ...options,
            })
        })
        return id
    },
    success(message: string | JSX.Element, { button, ...toastOptions }: ToastOptionsWithButton = {}) {
        const options = ensureToastId(toastOptions, 'success', message)
        const id = options.toastId!
        queueMicrotask(() => {
            if (cancelledIds.delete(id)) {
                return
            }
            toast.success(<ToastContent type="success" message={message} button={button} id={id} />, {
                icon: successIcon(),
                ...options,
            })
        })
        return id
    },
    warning(message: string | JSX.Element, { button, ...toastOptions }: ToastOptionsWithButton = {}) {
        posthog.capture('toast warning', {
            message: String(message),
            button: button?.label,
            toastId: toastOptions.toastId,
        })
        const options = ensureToastId(toastOptions, 'warning', message)
        const id = options.toastId!
        queueMicrotask(() => {
            if (cancelledIds.delete(id)) {
                return
            }
            toast.warning(<ToastContent type="warning" message={message} button={button} id={id} />, {
                icon: <IconWarning />,
                ...options,
            })
        })
        return id
    },
    error(message: string | JSX.Element, { button, hideButton, ...toastOptions }: ToastOptionsWithButton = {}) {
        // when used inside the posthog toolbar, `posthog.capture` isn't loaded
        // check if the function is available before calling it.
        if (posthog.capture) {
            posthog.capture('toast error', {
                message: String(message),
                button: button?.label,
                toastId: toastOptions.toastId,
            })
        }

        const options = ensureToastId(toastOptions, 'error', message)
        const id = options.toastId!
        queueMicrotask(() => {
            if (cancelledIds.delete(id)) {
                return
            }
            toast.error(
                <ToastContent
                    type="error"
                    message={withIncidentNote(message)}
                    // Show button if explicitly provided, or show GET_HELP_BUTTON unless hideButton is true
                    button={button !== undefined ? button : hideButton ? undefined : GET_HELP_BUTTON}
                    id={id}
                />,
                {
                    icon: <IconErrorOutline />,
                    ...options,
                }
            )
        })
        return id
    },
    promise(
        promise: Promise<any>,
        messages: {
            pending: string | JSX.Element
            /** A function is called when the promise settles, so it can read state that changed while it ran. */
            success: string | JSX.Element | ((data?: string) => string | JSX.Element)
            error: string | JSX.Element
        },
        { button, ...toastOptions }: ToastOptionsWithButton = {}
    ): Promise<any> {
        const options = ensureToastId(toastOptions, 'promise')
        const id = options.toastId
        // see https://fkhadra.github.io/react-toastify/promise
        return toast.promise<string | undefined, ToastError>(
            promise,
            {
                pending: {
                    render: <ToastContent type="info" message={messages.pending} button={button} id={id} />,
                    icon: <Spinner />,
                },
                success: {
                    render: ({ data }) => {
                        const success =
                            typeof messages.success === 'function' ? messages.success(data) : data || messages.success
                        return <ToastContent type="success" message={success} button={button} id={id} />
                    },
                    icon: successIcon(),
                },
                error: {
                    render: ({ data }) => {
                        return (
                            <ToastContent
                                type="error"
                                message={withIncidentNote(data?.message || messages.error)}
                                button={button}
                                id={id}
                            />
                        )
                    },
                    icon: <IconErrorOutline />,
                },
            },
            options
        )
    },
    updateToSuccess(
        id: number | string,
        message: string | JSX.Element,
        { button, ...toastOptions }: ToastOptionsWithButton = {}
    ): void {
        toast.update(id, {
            render: <ToastContent type="success" message={message} button={button} id={id} />,
            type: 'success',
            icon: successIcon(),
            // react-toastify drops null props so the container's defaults apply again. This is the
            // same reset its own promise() resolver does when leaving the loading state.
            isLoading: null,
            autoClose: null,
            closeOnClick: null,
            closeButton: null,
            draggable: null,
            ...toastOptions,
        } as UpdateOptions)
    },
    isActive(id: number | string): boolean {
        return toast.isActive(id)
    },
    dismiss(id?: number | string): void {
        // If a toast was created in this tick but hasn't been registered yet (due to
        // queueMicrotask deferral), mark the ID as cancelled so the microtask skips it.
        if (id) {
            cancelledIds.add(id)
        }
        toast.dismiss(id)
    },
}
