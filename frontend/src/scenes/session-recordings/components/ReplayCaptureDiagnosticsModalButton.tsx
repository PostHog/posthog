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
                data-attr="check-why-session-didnt-record"
            >
                Check why this session didn't record
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="Why didn't this session record?"
                width={600}
            >
                <ReplayCaptureDiagnosticsPanel eventProperties={eventProperties} />
            </LemonModal>
        </>
    )
}
