import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

export function AllowTrainingCallout({
    featureName,
    className,
}: {
    featureName: string
    className?: string
}): JSX.Element | null {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const { isHobby } = useValues(preflightLogic)
    const isFlagEnabled = useFeatureFlag('AI_TRAINING')
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (
        isHobby ||
        !isFlagEnabled ||
        restrictionReason ||
        currentOrganization?.is_ai_training_opted_in !== false ||
        currentOrganization.is_hipaa ||
        currentOrganization.is_ai_training_cta_shown === false
    ) {
        return null
    }

    const isLocked = !!currentOrganization.is_ai_training_locked
    const action = isLocked
        ? { children: 'Enable', to: urls.settings('organization-details', 'organization-ai-training-opt-out') }
        : {
              children: 'Enable',
              onClick: () => updateOrganization({ is_ai_training_opted_in: true }),
              loading: currentOrganizationLoading,
              'data-attr': 'allow-training-callout-opt-in',
          }

    return (
        <LemonBanner type="info" action={action} className={className ?? 'my-3'}>
            Help us make {featureName} better for you by enabling training on anonymized data.
        </LemonBanner>
    )
}
