import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { ProjectFactChip } from './ProjectFactChip'

export function ProjectTokenChip(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

    if (!currentTeam?.api_token) {
        return null
    }
    return (
        <ProjectFactChip
            label="Project token"
            value={currentTeam.api_token}
            copyTooltip="Copy project token"
            copyThing="project token"
            action="copy_project_token"
        />
    )
}
