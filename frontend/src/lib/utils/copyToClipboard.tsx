import posthog from 'posthog-js'

import { IconCopy } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

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
        lemonToast.info(`Copied ${description} to clipboard`, {
            icon: <IconCopy />,
        })
    }

    const notifyFailure = (error: unknown): void => {
        // Capture the reason so the failure rate is measurable, not swallowed.
        posthog.captureException(error, { copyToClipboardDescription: description })
        lemonToast.error(`Could not copy ${description} to clipboard. Try again in a moment.`)
    }

    try {
        await navigator.clipboard.writeText(value)
        notifySuccess()
        return true
    } catch (clipboardError) {
        // If the Clipboard API fails, fallback to textarea method
        try {
            const textArea = document.createElement('textarea')
            textArea.value = value
            document.body.appendChild(textArea)
            textArea.select()
            const copied = document.execCommand('copy')
            document.body.removeChild(textArea)
            if (!copied) {
                // execCommand returns false without throwing, so an unchecked fallback claims success on an empty clipboard.
                notifyFailure(clipboardError)
                return false
            }
            notifySuccess()
            return true
        } catch (fallbackError) {
            notifyFailure(fallbackError)
            return false
        }
    }
}
