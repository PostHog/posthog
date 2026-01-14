import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { ResourcesAccessControls } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourcesAccessControls'

export function TeamAccessControl(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="space-y-6">
            <p>Control access to your project and its resources</p>
            {currentTeam?.id ? <ResourcesAccessControls projectId={`${currentTeam.id}`} /> : null}
        </div>
    )
}
