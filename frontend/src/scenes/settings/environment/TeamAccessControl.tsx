import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'
import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic, getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { AccessControlTerraformExport } from 'scenes/settings/environment/AccessControlTerraformExport'
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const showResolutionBanner =
        featureFlags[FEATURE_FLAGS.ACCESS_CONTROL_RESOLUTION_PREVIEW] &&
        !currentOrganization?.uses_most_specific_access_resolution &&
        isAdminOrOwner &&
        hasAvailableFeature(AvailableFeature.ACCESS_CONTROL)
    const resolutionBannerMessage =
        getFeatureFlagPayload(FEATURE_FLAGS.ACCESS_CONTROL_RESOLUTION_PREVIEW)?.message ??
        'Access control will start using the most specific rule. Review the changes before they take effect.'
    const resourceAccessControls = currentTeam?.id ? (
        <ResourcesAccessControlsV2 projectId={`${currentTeam.id}`} tabsRightSlot={<AccessControlTerraformExport />} />
    ) : null

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-4">
                {showResolutionBanner && (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <ItemDescription>{resolutionBannerMessage}</ItemDescription>
                        </ItemContent>
                        <ItemActions>
                            <Button
                                variant="outline"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.settings('organization-access-resolution')} />}
                                data-attr="access-resolution-banner-review"
                            >
                                Review changes
                            </Button>
                        </ItemActions>
                    </Item>
                )}
                {resourceAccessControls}
            </div>
        )
    }

    return (
        <div className="space-y-6">
            {showResolutionBanner && (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Review changes',
                        to: urls.settings('organization-access-resolution'),
                        'data-attr': 'access-resolution-banner-review',
                    }}
                >
                    {resolutionBannerMessage}
                </LemonBanner>
            )}
            {resourceAccessControls}
        </div>
    )
}
