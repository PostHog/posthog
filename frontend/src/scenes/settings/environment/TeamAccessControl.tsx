import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { ResourcesAccessControls } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourcesAccessControls'

export function TeamAccessControl(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="space-y-6">
            <div className="space-y-2">
                <p className="mb-0">
                    Use access control rules to manage access for this project and its resources. You can set defaults
                    for everyone, specific roles, or specific members.
                </p>
            </div>

            {currentTeam?.id ? <ResourcesAccessControls projectId={`${currentTeam.id}`} /> : null}
        </div>
    )
}
