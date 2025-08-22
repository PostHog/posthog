import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { AccessControlObject } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlObject'
import { ResourcesAccessControls } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourcesAccessControls'

export function TeamAccessControl(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

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
