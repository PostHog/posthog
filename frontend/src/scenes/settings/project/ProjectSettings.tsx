import { useActions, useValues } from 'kea'
import { useState } from 'react'

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

    return (
        <div className="deprecated-space-y-4 max-w-160">
            <LemonInput value={name} onChange={setName} disabled={currentProjectLoading} />
            <LemonButton
                type="primary"
                onClick={() => updateCurrentProject({ name })}
                disabled={!name || !currentProject || name === currentProject.name || !!restrictedReason}
                disabledReason={restrictedReason}
                loading={currentProjectLoading}
            >
                Rename project
            </LemonButton>
        </div>
    )
}
