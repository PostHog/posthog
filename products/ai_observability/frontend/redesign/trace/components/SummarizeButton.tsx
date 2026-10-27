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
    const button = (
        <AccessControlAction
            resourceType={AccessControlResourceType.LlmAnalytics}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                type={type}
                size="small"
                onClick={consentGiven ? onClick : undefined}
                loading={loading}
                data-attr={dataAttr}
                disabledReason={
                    consentGiven ? undefined : 'Your organization needs to approve AI data processing first'
                }
            >
                {label}
            </LemonButton>
        </AccessControlAction>
    )
    if (consentGiven) {
        return button
    }
    // The popover asks for approval and runs the request once it is given.
    return (
        <AIConsentPopoverWrapper showArrow onApprove={onClick} hidden={loading}>
            {button}
        </AIConsentPopoverWrapper>
    )
}
