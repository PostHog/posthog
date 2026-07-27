import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import { AI_TRAINING_URL } from './aiTrainingConstants'
import { ORG_ADMIN_REQUIRED_TOOLTIP } from './organizationSettingsConstants'

function AITrainingDescription({ isHipaa, isLocked }: { isHipaa: boolean; isLocked: boolean }): JSX.Element {
    if (isHipaa) {
        return (
            <p className="mb-2 text-sm text-secondary">
                You are opted out of internal AI training because you are compliant with HIPAA.
            </p>
        )
    }

    if (isLocked) {
        return (
            <p className="mb-2 text-sm text-secondary">
                Your organization's internal AI training preference is fixed by your contract and cannot be changed.
                Please contact us if you need to discuss this.
            </p>
        )
    }

    return (
        <div className="mb-2 text-sm text-secondary">
            <p>
                Enable PostHog to use anonymized aggregated data to train AI features that benefit all PostHog
                customers. <strong>Your and your customers' data stays with PostHog.</strong>
            </p>
            <p className="mt-2">Opting out means that you cannot access certain AI features.</p>
        </div>
    )
}

export function OrganizationAITrainingOptOut(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const isHipaa = !!currentOrganization?.is_hipaa
    const isLocked = !!currentOrganization?.is_ai_training_locked

    const disabledReason = isHipaa
        ? 'HIPAA organizations are always opted out of AI training. Please contact us if this needs to change.'
        : isLocked
          ? 'Please contact us to change this setting.'
          : restrictionReason
            ? ORG_ADMIN_REQUIRED_TOOLTIP
            : undefined

    const checked = !isHipaa && !!currentOrganization?.is_ai_training_opted_in

    return (
        <div className="max-w-160">
            <AITrainingDescription isHipaa={isHipaa} isLocked={isLocked} />
            <div className="my-4">
                <LemonSwitch
                    label="Enable AI training on anonymized data"
                    data-attr="organization-ai-training-opt-in"
                    onChange={(value) => {
                        updateOrganization({ is_ai_training_opted_in: value })
                    }}
                    checked={checked}
                    disabledReason={disabledReason}
                    loading={currentOrganizationLoading}
                    bordered
                />
            </div>
            <LemonButton type="primary" className="inline-block" sideIcon={<IconExternal />} to={AI_TRAINING_URL}>
                What's this?
            </LemonButton>
        </div>
    )
}
