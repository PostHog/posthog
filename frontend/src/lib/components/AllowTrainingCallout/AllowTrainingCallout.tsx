import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
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

    if (isHobby || !isFlagEnabled || restrictionReason || !currentOrganization || currentOrganization.is_hipaa) {
        return null
    }

    const settingsUrl = urls.settings('organization-details', 'organization-ai-training-opt-out')

    // Opted in: give the notice these organizations never got by email, and record that they saw it.
    if (currentOrganization.is_ai_training_opted_in === true) {
        if (currentOrganization.ai_training_notice_acknowledged_at) {
            return null
        }
        return (
            <LemonBanner
                type="info"
                action={{ children: 'Review settings', to: settingsUrl }}
                onClose={() => updateOrganization({ acknowledge_ai_training_notice: true })}
                className={className ?? 'my-3'}
            >
                Your organization is opted in to AI training, so anonymized data helps improve {featureName}. Your and
                your customers' data stays with PostHog. You can change this in settings.
            </LemonBanner>
        )
    }

    // Opted out: invite admins to enable, unless the invite was dismissed.
    if (
        currentOrganization.is_ai_training_opted_in === false &&
        currentOrganization.is_ai_training_cta_shown !== false
    ) {
        const action = currentOrganization.is_ai_training_locked
            ? { children: 'Enable', to: settingsUrl }
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

    return null
}
