import posthog from 'posthog-js'

import { IconCopy } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseCopyButton({
    value,
    thing,
    target,
    iconOnly = false,
}: {
    value: string
    thing: string
    // The `target` property of `warehouse connect copied`: a connection field or a snippet key.
    target: string
    iconOnly?: boolean
}): JSX.Element {
    return (
        <Button
            size={iconOnly ? 'icon-sm' : 'sm'}
            aria-label={`Copy ${thing}`}
            data-attr={`warehouse-connect-copy-${target}`}
            onClick={() => {
                posthog.capture('warehouse connect copied', { target })
                void copyToClipboard(value, thing)
            }}
        >
            <IconCopy />
            {!iconOnly && 'Copy'}
        </Button>
    )
}
