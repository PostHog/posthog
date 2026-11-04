import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export interface SummarizeButtonProps {
    label: string
    onClick: () => void
    loading: boolean
    consentGiven: boolean
    dataAttr: string
    type: 'primary' | 'secondary'
}

export function SummarizeButton({
    label,
    onClick,
    loading,
    consentGiven,
    dataAttr,
    type,
}: SummarizeButtonProps): JSX.Element {
    const [consentRequested, setConsentRequested] = useState(false)
    const button = (
        <AccessControlAction
            resourceType={AccessControlResourceType.LlmAnalytics}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                type={type}
                size="small"
                onClick={consentGiven ? onClick : () => setConsentRequested(true)}
                loading={loading}
                data-attr={dataAttr}
            >
                {label}
            </LemonButton>
        </AccessControlAction>
    )
    if (consentGiven) {
        return button
    }
    // The popover opens on click, also after an earlier dismissal, and runs the request once approval is given.
    return (
        <AIConsentPopoverWrapper
            showArrow
            ignoreDismissal
            hidden={!consentRequested || loading}
            onApprove={() => {
                setConsentRequested(false)
                onClick()
            }}
            onDismiss={() => setConsentRequested(false)}
        >
            {button}
        </AIConsentPopoverWrapper>
    )
}
