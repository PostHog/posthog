import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

/** Tooltip content for a failed sync: the error text plus a one-click copy button. */
export function syncErrorTooltip(error: string): JSX.Element {
    return (
        <div className="flex items-start gap-1">
            <span className="whitespace-pre-wrap">{error}</span>
            <LemonButton
                size="xsmall"
                icon={<IconCopy />}
                noPadding
                tooltip="Copy error"
                onClick={() => void copyToClipboard(error, 'error message')}
            />
        </div>
    )
}
