import { useValues } from 'kea'
import { useState } from 'react'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

export interface AIConsentGate {
    onClick: () => void
    /** Spread onto `AIConsentPopoverWrapper`, together with `ignoreDismissal`. */
    popover: { hidden: boolean; onApprove: () => void; onDismiss: () => void }
}

/**
 * Opens the AI consent popover only when a person without consent clicks, and runs the action once
 * they approve. Without `hidden`, a wrapper with `ignoreDismissal` stays open from the first render
 * and Cancel cannot close it.
 */
export function useAIConsentGate(run: () => void): AIConsentGate {
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)

    return {
        onClick: () => (dataProcessingAccepted ? run() : setConsentRequested(true)),
        popover: {
            hidden: !consentRequested,
            onApprove: () => {
                setConsentRequested(false)
                run()
            },
            onDismiss: () => setConsentRequested(false),
        },
    }
}
