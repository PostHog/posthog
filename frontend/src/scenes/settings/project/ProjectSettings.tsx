import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { projectLogic } from 'scenes/projectLogic'

export function ProjectDisplayName(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { updateCurrentProject } = useActions(projectLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const [name, setName] = useState(currentProject?.name || '')

    useEffect(() => {
        setName(currentProject?.name || '')
    }, [currentProject?.name])

    const renameDisabledReason = restrictedReason
        ? restrictedReason
        : currentProjectLoading
          ? 'Loading project…'
          : !name
            ? 'Enter a name to rename the project'
            : currentProject && name === currentProject.name
              ? 'Enter a different name to rename the project'
              : null

    return (
        <div className="deprecated-space-y-4 max-w-160">
            <LemonInput
                value={name}
                onChange={setName}
                disabledReason={currentProjectLoading ? 'Loading project…' : restrictedReason}
            />
            <LemonButton
                type="primary"
                onClick={() => updateCurrentProject({ name })}
                disabledReason={renameDisabledReason}
                loading={currentProjectLoading}
            >
                Rename project
            </LemonButton>
        </div>
    )
}
