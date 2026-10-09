import { useValues } from 'kea'
import { Suspense, useState } from 'react'

import { IconCode2 } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useKeepMountedWhileOpen } from 'lib/hooks/useKeepMountedWhileOpen'
import { featureFlagLogic, getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ResourcesAccessControlsV2 } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourceAccessControlsV2'
import { AvailableFeature } from '~/types'

// Loaded on demand like the dashboard export, so the exporters stay out of the settings bundle
const TerraformExportModal = lazyWithRetry(() =>
    import('lib/components/TerraformExporter/TerraformExportModal').then((m) => ({ default: m.TerraformExportModal }))
)

export function TeamAccessControl(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentOrganization, isAdminOrOwner } = useValues(organizationLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const [terraformModalOpen, setTerraformModalOpen] = useState(false)
    const shouldRenderTerraform = useKeepMountedWhileOpen(terraformModalOpen)

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
                        currentOrganization?.id ? (
                            <>
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    className="group/terraform-button"
                                    icon={
                                        <IconCode2 className="text-secondary group-hover/terraform-button:text-primary" />
                                    }
                                    onClick={() =>
                                        guardAvailableFeature(AvailableFeature.ACCESS_CONTROL, () =>
                                            setTerraformModalOpen(true)
                                        )
                                    }
                                    data-attr="access-control-manage-terraform"
                                >
                                    <span className="font-normal text-secondary group-hover/terraform-button:text-primary">
                                        Manage with Terraform
                                    </span>
                                </LemonButton>
                                {shouldRenderTerraform ? (
                                    <Suspense fallback={null}>
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
                                    </Suspense>
                                ) : null}
                            </>
                        ) : undefined
                    }
                />
            ) : null}
        </div>
    )
}
