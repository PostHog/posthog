// PROTOTYPE, throwaway: variant J, a row on the scanner's Alerts tab that emails the person in each match.
import { IconLetter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { PROTOTYPE_SOURCES, useMessagingCtaVariant } from './messagingCtaPrototype'
import { openScannerWorkflow } from './scannerWorkflowPrototype'

export function VisionAlertsMessageRow({
    scanner,
}: {
    scanner: { id: string; scanner_type?: string }
}): JSX.Element | null {
    const variant = useMessagingCtaVariant()

    if (variant !== 'J') {
        return null
    }

    return (
        <div
            className="flex items-center justify-between gap-2 flex-wrap border rounded px-3 py-2 bg-surface-primary"
            data-attr="vision-alerts-message-row"
        >
            <span className="flex items-center gap-2 min-w-0">
                <IconLetter className="text-lg shrink-0 text-secondary" />
                <span className="flex flex-col">
                    <span className="font-semibold">Email the person in each match</span>
                    <span className="text-xs text-secondary">
                        Alerts tell your team. A workflow can email the person the scanner flagged.
                    </span>
                </span>
            </span>
            <LemonButton
                type="secondary"
                size="small"
                onClick={() => openScannerWorkflow(scanner, PROTOTYPE_SOURCES.visionAlerts)}
                data-attr="vision-alerts-message"
            >
                Set up an email
            </LemonButton>
        </div>
    )
}
