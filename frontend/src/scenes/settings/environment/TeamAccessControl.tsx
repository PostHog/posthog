import { useValues } from 'kea'
import { useState } from 'react'

import { IconCode2 } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { TerraformExportModal } from 'lib/components/TerraformExporter/TerraformExportModal'
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
    const [terraformModalOpen, setTerraformModalOpen] = useState(false)

    return (
        <div className="space-y-6">
            {featureFlags[FEATURE_FLAGS.ACCESS_CONTROL_RESOLUTION_PREVIEW] &&
                !currentOrganization?.uses_most_specific_access_resolution &&
                isAdminOrOwner &&
                hasAvailableFeature(AvailableFeature.ACCESS_CONTROL) && (
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
            {currentTeam?.id ? (
                <ResourcesAccessControlsV2
                    projectId={`${currentTeam.id}`}
                    tabsRightSlot={
                        currentOrganization?.id && hasAvailableFeature(AvailableFeature.ACCESS_CONTROL) ? (
                            <>
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    className="group/terraform-button"
                                    icon={
                                        <IconCode2 className="text-secondary group-hover/terraform-button:text-primary" />
                                    }
                                    onClick={() => setTerraformModalOpen(true)}
                                    data-attr="access-control-manage-with-terraform"
                                >
                                    <span className="font-normal text-secondary group-hover/terraform-button:text-primary">
                                        Manage with Terraform
                                    </span>
                                </LemonButton>
                                <TerraformExportModal
                                    isOpen={terraformModalOpen}
                                    onClose={() => setTerraformModalOpen(false)}
                                    resource={{
                                        type: 'access_control',
                                        data: {
                                            projectId: currentTeam.id,
                                            projectName: currentTeam.name,
                                            organizationId: currentOrganization.id,
                                        },
                                    }}
                                    data-attr="access-control-terraform-modal"
                                />
                            </>
                        ) : undefined
                    }
                />
            ) : null}
        </div>
    )
}
