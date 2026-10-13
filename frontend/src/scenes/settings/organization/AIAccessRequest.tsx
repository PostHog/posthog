import { useActions, useValues } from 'kea'

import { IconArrowRight, IconCheck } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { aiConsentLogic } from './aiConsentLogic'

/**
 * The path forward for a member who cannot approve AI data processing themselves: ask an
 * organization admin to do it. Shared by every surface that gates on consent, so a non-admin gets
 * the same working affordance wherever the gate appears.
 */
export function AIAccessRequest({ size = 'xsmall' }: { size?: 'xsmall' | 'small' }): JSX.Element {
    const { requestingAiAccess, aiAccessRequested } = useValues(aiConsentLogic)
    const { requestAiAccess } = useActions(aiConsentLogic)

    // An inline confirmation rather than a spent button, so a repeat visit reads as "already asked".
    if (aiAccessRequested) {
        return (
            <p className="flex items-start gap-1.5 m-0 text-xs text-muted">
                <IconCheck className="shrink-0 mt-0.5 text-success" />
                <span>Request sent. Your organization admins have been notified and can enable PostHog AI.</span>
            </p>
        )
    }

    return (
        <LemonButton
            data-attr="ai-access-request"
            type="primary"
            size={size}
            onClick={() => requestAiAccess()}
            loading={requestingAiAccess}
            sideIcon={<IconArrowRight />}
        >
            Request access
        </LemonButton>
    )
}
