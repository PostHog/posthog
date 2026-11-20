import { IconX } from '@posthog/icons'

import { Button } from 'lib/ui/quill'

export function BannerDismissButton({ onDismiss }: { onDismiss: () => void }): JSX.Element {
    return (
        <Button variant="default" size="icon-sm" aria-label="Dismiss" tooltip="Dismiss" onClick={onDismiss}>
            <IconX />
        </Button>
    )
}
