import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic, getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ResourcesAccessControlsV2 } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourceAccessControlsV2'
import { AvailableFeature } from '~/types'

export function TeamAccessControl(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentOrganization, isAdminOrOwner } = useValues(organizationLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const canSeePreview = isAdminOrOwner && hasAvailableFeature(AvailableFeature.ACCESS_CONTROL)
    const alreadyEnabled = !!currentOrganization?.uses_most_specific_access_resolution

    return (
        <div className="space-y-6">
            {canSeePreview && alreadyEnabled && (
                <LemonBanner
                    type="success"
                    action={{
                        children: 'See what changed',
                        to: urls.settings('organization-access-resolution'),
                        'data-attr': 'access-resolution-banner-enabled',
                    }}
                >
                    Access control uses the most specific rule for your organization.
                </LemonBanner>
            )}
            {canSeePreview && !alreadyEnabled && featureFlags[FEATURE_FLAGS.ACCESS_CONTROL_RESOLUTION_PREVIEW] && (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Review changes',
                        to: urls.settings('organization-access-resolution'),
                        'data-attr': 'access-resolution-banner-review',
                    }}
                >
                    {getFeatureFlagPayload(FEATURE_FLAGS.ACCESS_CONTROL_RESOLUTION_PREVIEW)?.message ??
                        'Access control will start using the most specific rule. Review the changes before they take effect.'}
                </LemonBanner>
            )}
            {currentTeam?.id ? <ResourcesAccessControlsV2 projectId={`${currentTeam.id}`} /> : null}
        </div>
    )
}
