import { useActions, useValues } from 'kea'

import { LemonButton, LemonInputSelect } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { projectsGridLogic } from './projectsGridLogic'

export function ProjectsGridPicker(): JSX.Element {
    const { pickedTeamIds } = useValues(projectsGridLogic)
    const { setPickedTeamIds, resetPickedTeamIds } = useActions(projectsGridLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeamId } = useValues(teamLogic)

    const options = (currentOrganization?.teams ?? [])
        .filter((t) => t.id !== currentTeamId)
        .map((t) => ({ key: String(t.id), label: t.name }))

    return (
        <div className="flex items-center gap-2">
            <LemonInputSelect
                placeholder="Add projects…"
                value={pickedTeamIds.map(String)}
                options={options}
                onChange={(values) => setPickedTeamIds(values.map(Number))}
                mode="multiple"
                data-attr="projects-grid-picker"
            />
            {pickedTeamIds.length > 0 && (
                <LemonButton size="small" type="tertiary" onClick={() => resetPickedTeamIds()}>
                    Reset
                </LemonButton>
            )}
        </div>
    )
}
