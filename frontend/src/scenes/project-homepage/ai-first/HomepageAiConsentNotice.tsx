import { useAsyncActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { AIAccessRequest } from 'scenes/settings/organization/AIAccessRequest'
import { openAIConsentLegalDialog } from 'scenes/settings/organization/aiConsentCopy'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

export function HomepageAiConsentNotice({ onApproved }: { onApproved?: () => void }): JSX.Element {
    const { dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const { acceptDataProcessing } = useAsyncActions(aiConsentLogic)

    const isAdmin = !dataProcessingApprovalDisabledReason
    return (
        <div
            className="border border-primary rounded-lg bg-surface-primary p-4 flex flex-col gap-2"
            data-attr="homepage-ai-consent-notice"
        >
            <p className="font-medium text-pretty m-0">
                {isAdmin
                    ? 'PostHog AI needs your approval to potentially process identifying user data with external AI providers.'
                    : 'PostHog AI needs an organization admin to approve processing identifying user data with external AI providers.'}
            </p>
            <p className="text-muted text-xs m-0">Your data won't be used for training third-party models.</p>
            {isAdmin ? (
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() =>
                        openAIConsentLegalDialog({
                            onConfirm: async () => {
                                await acceptDataProcessing()
                                onApproved?.()
                            },
                        })
                    }
                    sideIcon={<IconArrowRight />}
                >
                    I allow AI analysis in this organization
                </LemonButton>
            ) : (
                <div className="flex">
                    <AIAccessRequest size="small" />
                </div>
            )}
        </div>
    )
}
