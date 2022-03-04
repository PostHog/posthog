import React from 'react'
import { toast, ToastOptions } from 'react-toastify'
import { IconCheckmark, IconErrorOutline, IconInfo, IconWarningAmber } from './icons'
import { LemonButton } from './LemonButton'

interface ToastButton {
    label: string
    action: () => void
}

interface ToastOptionsWithButton extends ToastOptions {
    button?: ToastButton
}

const GET_HELP_BUTTON: ToastButton = {
    label: 'Get help',
    action: () => {
        window.open('https://posthog.com/support?utm_medium=in-product&utm_campaign=error-toast', '_blank')
    },
}

interface ToastContentProps {
    message: string | JSX.Element
    button?: ToastButton
    id?: number | string
}

function ToastContent({ message, button, id }: ToastContentProps): JSX.Element {
    return (
        <div className="flex-center">
            <span style={{ flexGrow: 1 }}>{message}</span>
            {button && (
                <LemonButton
                    onClick={() => {
                        button.action()
                        toast.dismiss(id)
                    }}
                    type="secondary"
                    compact
                >
                    {button.label}
                </LemonButton>
            )}
        </div>
    )
}

function ensureToastId(toastOptions: ToastOptions): void {
    if (!toastOptions.toastId) {
        toastOptions.toastId = `lemon-${Math.round(Math.random() * 10000000)}`
    }
}

export const lemonToast = {
    info(message: string | JSX.Element, { button, ...toastOptions }: ToastOptionsWithButton = {}): void {
        ensureToastId(toastOptions)
        toast.info(<ToastContent message={message} button={button} id={toastOptions.toastId} />, {
            icon: <IconInfo />,
            ...toastOptions,
        })
    },
    success(message: string | JSX.Element, { button, ...toastOptions }: ToastOptionsWithButton = {}): void {
        ensureToastId(toastOptions)
        toast.success(<ToastContent message={message} button={button} id={toastOptions.toastId} />, {
            icon: <IconCheckmark />,
            ...toastOptions,
        })
    },
    warning(message: string | JSX.Element, { button, ...toastOptions }: ToastOptionsWithButton = {}): void {
        ensureToastId(toastOptions)
        toast.warning(<ToastContent message={message} button={button} id={toastOptions.toastId} />, {
            icon: <IconWarningAmber />,
            ...toastOptions,
        })
    },
    error(message: string | JSX.Element, { button, ...toastOptions }: ToastOptionsWithButton = {}): void {
        ensureToastId(toastOptions)
        toast.error(<ToastContent message={message} button={button || GET_HELP_BUTTON} id={toastOptions.toastId} />, {
            icon: <IconErrorOutline />,
            ...toastOptions,
        })
    },
    dismiss(id?: number | string): void {
        toast.dismiss(id)
    },
}
