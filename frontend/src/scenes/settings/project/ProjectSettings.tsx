import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { projectLogic } from 'scenes/projectLogic'

export function ProjectDisplayName(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { updateCurrentProject } = useActions(projectLogic)

    const [name, setName] = useState(currentProject?.name || '')

    return (
        <div className="deprecated-space-y-4 max-w-160">
            <LemonInput value={name} onChange={setName} disabled={currentProjectLoading} />
            <LemonButton
                type="primary"
                onClick={() => updateCurrentProject({ name })}
                disabled={!name || !currentProject || name === currentProject.name}
                loading={currentProjectLoading}
            >
                Rename project
            </LemonButton>
        </div>
    )
}
