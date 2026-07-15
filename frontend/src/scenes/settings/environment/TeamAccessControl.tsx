import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { ResourcesAccessControlsV2 } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourceAccessControlsV2'

export function TeamAccessControl(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

    return currentTeam?.id ? <ResourcesAccessControlsV2 projectId={`${currentTeam.id}`} /> : null
}
