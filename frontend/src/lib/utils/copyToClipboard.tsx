import { IconCopy } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

export async function copyToClipboard(
    value: string,
    description: string = 'text',
    { silent = false, html }: { silent?: boolean; html?: string } = {}
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

    // Writing both formats lets a paste target that understands HTML keep the formatting, while
    // plain-text targets still receive `value`. Browser support for `text/html` in a ClipboardItem
    // is not universal, so a failure here falls through to the plain-text write below rather than
    // failing the copy.
    if (html && typeof ClipboardItem !== 'undefined' && navigator.clipboard.write) {
        try {
            await navigator.clipboard.write([
                new ClipboardItem({
                    'text/html': new Blob([html], { type: 'text/html' }),
                    'text/plain': new Blob([value], { type: 'text/plain' }),
                }),
            ])
            notifySuccess()
            return true
        } catch {
            // Fall through to the plain-text paths.
        }
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
