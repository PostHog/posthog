// PROTOTYPE, throwaway: variant I, a scanner header button that emails each person the scanner flags.
import { IconSend } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { PROTOTYPE_SOURCES, useMessagingCtaVariant } from './messagingCtaPrototype'
import { openScannerWorkflow } from './scannerWorkflowPrototype'

export function VisionScannerMessageAction({
    scanner,
}: {
    scanner: { id: string; scanner_type?: string }
}): JSX.Element | null {
    const variant = useMessagingCtaVariant()

    if (variant !== 'I') {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconSend />}
            onClick={() => openScannerWorkflow(scanner, PROTOTYPE_SOURCES.visionHeader)}
            tooltip="Opens a workflow that emails each person this scanner flags. Nothing sends until you turn it on."
            data-attr="vision-scanner-message"
        >
            Email people it flags
        </LemonButton>
    )
}
