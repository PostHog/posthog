import { IconCopy } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import { writeToClipboard } from 'lib/utils/writeToClipboard'

export async function copyToClipboard(
    value: string,
    description: string = 'text',
    { silent = false, html }: { silent?: boolean; html?: string } = {}
): Promise<boolean> {
    const outcome = await writeToClipboard(value, html)

    if (outcome === 'unavailable') {
        lemonToast.warning('Oops! Clipboard capabilities are only available over HTTPS or on localhost')
        return false
    }
    if (outcome === 'failed') {
        lemonToast.error(`Could not copy ${description} to clipboard`)
        return false
    }
    if (!silent) {
        lemonToast.info(`Copied ${description} to clipboard`, {
            icon: <IconCopy />,
        })
    }
    return true
}
