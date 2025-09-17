import posthog from 'posthog-js'
import { ToastOptions, ToastContentProps as ToastifyRenderProps, toast } from 'react-toastify'

import { IconCheckCircle, IconInfo, IconWarning, IconX } from '@posthog/icons'

import { LemonButton } from '../LemonButton'
import { Spinner } from '../Spinner'
import { IconErrorOutline } from '../icons'

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

interface ToastButton {
    label: string
    action: (() => void) | (() => Promise<void>)
    dataAttr?: string
}

interface ToastOptionsWithButton extends ToastOptions {
    button?: ToastButton
    hideButton?: boolean
}

export const GET_HELP_BUTTON: ToastButton = {
    label: 'Get help',
    action: () => {
        window.open('https://posthog.com/support?utm_medium=in-product&utm_campaign=error-toast', '_blank')
    },
}

export interface ToastContentProps {
    type: 'info' | 'success' | 'warning' | 'error'
    message: string | JSX.Element
    button?: ToastButton
    id?: number | string
}

export function ToastContent({ type, message, button, id }: ToastContentProps): JSX.Element {
    return (
        <div className="flex items-center" data-attr={`${type}-toast`}>
            <span className="grow overflow-hidden text-ellipsis">{message}</span>
            {button && (
                <LemonButton
                    onClick={() => {
                        void button.action()
                        toast.dismiss(id)
                    }}
                    type="secondary"
                    size="small"
                    data-attr={button.dataAttr}
                >
                    {button.label}
                </LemonButton>
            )}
        </div>
    )
}

function ensureToastId(toastOptions: ToastOptions): ToastOptions {
    return toastOptions.toastId
        ? toastOptions
        : { ...toastOptions, toastId: `lemon-${Math.round(Math.random() * 10000000)}` }
}

export const lemonToast = {
    info(message: string | JSX.Element, { button, ...toastOptions }: ToastOptionsWithButton = {}): void {
        toastOptions = ensureToastId(toastOptions)
        toast.info(<ToastContent type="info" message={message} button={button} id={toastOptions.toastId} />, {
            icon: <IconInfo />,
            ...toastOptions,
        })
    },
    success(message: string | JSX.Element, { button, ...toastOptions }: ToastOptionsWithButton = {}): void {
        toastOptions = ensureToastId(toastOptions)
        toast.success(<ToastContent type="success" message={message} button={button} id={toastOptions.toastId} />, {
            icon: <IconCheckCircle />,
            ...toastOptions,
        })
    },
    warning(message: string | JSX.Element, { button, ...toastOptions }: ToastOptionsWithButton = {}): void {
        posthog.capture('toast warning', {
            message: String(message),
            button: button?.label,
            toastId: toastOptions.toastId,
        })
        toastOptions = ensureToastId(toastOptions)
        toast.warning(<ToastContent type="warning" message={message} button={button} id={toastOptions.toastId} />, {
            icon: <IconWarning />,
            ...toastOptions,
        })
    },
    error(message: string | JSX.Element, { button, hideButton, ...toastOptions }: ToastOptionsWithButton = {}): void {
        // when used inside the posthog toolbar, `posthog.capture` isn't loaded
        // check if the function is available before calling it.
        if (posthog.capture) {
            posthog.capture('toast error', {
                message: String(message),
                button: button?.label,
                toastId: toastOptions.toastId,
            })
        }

        toastOptions = ensureToastId(toastOptions)
        toast.error(
            <ToastContent
                type="error"
                message={message}
                // Show button if explicitly provided, or show GET_HELP_BUTTON unless hideButton is true
                button={button !== undefined ? button : hideButton ? undefined : GET_HELP_BUTTON}
                id={toastOptions.toastId}
            />,
            {
                icon: <IconErrorOutline />,
                ...toastOptions,
            }
        )
    },
    promise(
        promise: Promise<any>,
        messages: { pending: string | JSX.Element; success: string | JSX.Element; error: string | JSX.Element },
        icons: { pending?: JSX.Element; success?: JSX.Element; error?: JSX.Element } = {},
        { button, ...toastOptions }: ToastOptionsWithButton = {}
    ): Promise<any> {
        toastOptions = ensureToastId(toastOptions)
        // see https://fkhadra.github.io/react-toastify/promise
        return toast.promise(
            promise,
            {
                pending: {
                    render: <ToastContent type="info" message={messages.pending} button={button} />,
                    icon: icons.pending ?? <Spinner />,
                },
                success: {
                    render({ data }: ToastifyRenderProps<string>) {
                        return <ToastContent type="success" message={data || messages.success} button={button} />
                    },
                    icon: icons.success ?? <IconCheckCircle />,
                },
                error: {
                    render({ data }: ToastifyRenderProps<Error>) {
                        return <ToastContent type="error" message={data?.message || messages.error} button={button} />
                    },
                    icon: icons.error ?? <IconErrorOutline />,
                },
            },
            toastOptions
        )
    },
    dismiss(id?: number | string): void {
        toast.dismiss(id)
    },
}
