import { useActions, useValues } from 'kea'

import { IconTestTube } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { featurePreviewsLogic } from '~/layout/FeaturePreviews/featurePreviewsLogic'
import { AccessControlObject } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlObject'
import { ResourcesAccessControlsV2 } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourceAccessControlsV2'
import { ResourcesAccessControls } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourcesAccessControls'

export function TeamAccessControl(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { updateEarlyAccessFeatureEnrollment } = useActions(featurePreviewsLogic)

    const useAccessControlRedesign = featureFlags[FEATURE_FLAGS.RBAC_UI_REDESIGN]

    if (useAccessControlRedesign) {
        return (
            <div className="space-y-6">
                <div className="space-y-2">
                    <p className="mb-0">
                        Use access control rules to manage access for this project and its resources. You can set
                        defaults for everyone, specific roles, or specific members.
                    </p>
                </div>

                {currentTeam?.id ? <ResourcesAccessControlsV2 projectId={`${currentTeam.id}`} /> : null}

                <Link
                    onClick={(e) => {
                        e.preventDefault()
                        updateEarlyAccessFeatureEnrollment('rbac-ui-redesign', false)
                    }}
                >
                    I don't like this new UI, show me the old one
                </Link>
            </div>
        )
    }

    return (
        <div className="space-y-6">
            <LemonButton
                icon={<IconTestTube />}
                onClick={() => {
                    updateEarlyAccessFeatureEnrollment('rbac-ui-redesign', true)
                }}
                type="primary"
            >
                Try the new UI
            </LemonButton>
            <p>Control access to your project and its resources</p>
            <AccessControlObject
                resource="project"
                resource_id={`${currentTeam?.id}`}
                title="Project permissions"
                description="Use project permissions to assign project-wide access for individuals and roles."
            />
            <ResourcesAccessControls />
        </div>
    )
}
