import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'

export interface PersonDrawerToolbarProps {
    onClose: () => void
}

export function PersonDrawerToolbar({ onClose }: PersonDrawerToolbarProps): JSX.Element {
    return (
        <div className="flex min-w-0 flex-1 items-center gap-1">
            <span className="font-semibold">Person</span>
            <LemonButton
                className="ml-auto"
                size="small"
                icon={<IconX />}
                tooltip={
                    <>
                        Close <KeyboardShortcut escape />
                    </>
                }
                aria-label="Close"
                // pinned: autocapture dashboards select the close button by this value
                data-attr="ai-observability-person-drawer-close"
                onClick={onClose}
            />
        </div>
    )
}
