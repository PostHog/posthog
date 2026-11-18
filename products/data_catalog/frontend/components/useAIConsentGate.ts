import { useValues } from 'kea'
import { useState } from 'react'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

export interface AIConsentGate {
    onClick: () => void
    /** True while the popover waits for this person's answer. */
    consentOpen: boolean
    /** Spread onto `AIConsentPopoverWrapper`, together with `ignoreDismissal`. */
    popover: {
        hidden: boolean
        onApprove: () => void
        onDismiss: () => void
        onBeforeApprove?: () => void
        pendingRedirectUrl?: string
    }
}

export interface AIConsentGateOptions {
    /** Stores the click, because SSO reauthentication can unload the page before `onApprove` runs. */
    onBeforeApprove?: () => void
    /** Where to return after that reauthentication. */
    pendingRedirectUrl?: string
}

/**
 * Opens the AI consent popover only when a person without consent clicks, and runs the action once
 * they approve. Without `hidden`, a wrapper with `ignoreDismissal` stays open from the first render
 * and Cancel cannot close it.
 */
export function useAIConsentGate(run: () => void, options: AIConsentGateOptions = {}): AIConsentGate {
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)

    return {
        onClick: () => (dataProcessingAccepted ? run() : setConsentRequested(true)),
        consentOpen: consentRequested,
        popover: {
            hidden: !consentRequested,
            onApprove: () => {
                setConsentRequested(false)
                run()
            },
            onDismiss: () => setConsentRequested(false),
            ...options,
        },
    }
}
