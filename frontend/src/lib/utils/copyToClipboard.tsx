import { IconCopy } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

export async function copyToClipboard(value: string, description: string = 'text'): Promise<boolean> {
    if (!navigator.clipboard) {
        lemonToast.warning('Oops! Clipboard capabilities are only available over HTTPS or on localhost')
        return false
    }

    try {
        await navigator.clipboard.writeText(value)
        lemonToast.info(`Copied ${description} to clipboard`, {
            icon: <IconCopy />,
        })
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
            lemonToast.info(`Copied ${description} to clipboard`, {
                icon: <IconCopy />,
            })
            return true
        } catch (err) {
            lemonToast.error(`Could not copy ${description} to clipboard: ${err}`)
            return false
        }
    }
}
