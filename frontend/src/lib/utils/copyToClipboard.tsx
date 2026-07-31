import { IconCopy } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

// Tracks the toast from the most recent copy so it can be dismissed before showing the next one.
// Without this, toasts for different copied values stack for the full autoClose duration, and the
// one left on screen can describe an earlier click rather than the most recent one.
let lastCopyToastId: string | number | undefined

export async function copyToClipboard(
    value: string,
    description: string = 'text',
    { silent = false }: { silent?: boolean } = {}
): Promise<boolean> {
    if (!navigator.clipboard) {
        lemonToast.warning('Oops! Clipboard capabilities are only available over HTTPS or on localhost')
        return false
    }

    const notifySuccess = (): void => {
        if (silent) {
            return
        }
        if (lastCopyToastId !== undefined) {
            lemonToast.dismiss(lastCopyToastId)
        }
        lastCopyToastId = lemonToast.info(`Copied ${description} to clipboard`, {
            icon: <IconCopy />,
        })
    }

    try {
        await navigator.clipboard.writeText(value)
        notifySuccess()
        return true
    } catch {
        // If the Clipboard API fails, fallback to textarea method
        try {
            const textArea = document.createElement('textarea')
            textArea.value = value
            document.body.appendChild(textArea)
            textArea.select()
            document.execCommand('copy')
            document.body.removeChild(textArea)
            notifySuccess()
            return true
        } catch (err) {
            lemonToast.error(`Could not copy ${description} to clipboard: ${err}`)
            return false
        }
    }
}
