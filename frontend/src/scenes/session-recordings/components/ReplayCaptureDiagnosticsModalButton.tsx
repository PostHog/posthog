import { useState } from 'react'

import { IconVideoCamera } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { ReplayCaptureDiagnosticsPanel } from './ReplayCaptureDiagnosticsPanel'

export function ReplayCaptureDiagnosticsModalButton({
    eventProperties,
}: {
    eventProperties: Record<string, any>
}): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconVideoCamera />}
                onClick={() => setIsOpen(true)}
                data-attr="check-session-recording-status"
            >
                Check session recording status
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="Session recording diagnosis"
                width={600}
            >
                <ReplayCaptureDiagnosticsPanel eventProperties={eventProperties} />
            </LemonModal>
        </>
    )
}
