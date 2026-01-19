import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlObject } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlObject'
import { ResourcesAccessControlsV2 } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourceAccessControlsV2'
import { ResourcesAccessControls } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourcesAccessControls'

export function TeamAccessControl(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

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
            </div>
        )
    }

    return (
        <div className="space-y-6">
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
