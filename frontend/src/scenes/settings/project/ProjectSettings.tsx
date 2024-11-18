import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { projectLogic } from 'scenes/projectLogic'

export function ProjectDisplayName(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { updateCurrentProject } = useActions(projectLogic)

    const [name, setName] = useState(currentProject?.name || '')

    return (
        <div className="space-y-4 max-w-160">
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

export function ProjectProductDescription(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { updateCurrentProject } = useActions(projectLogic)

    const [description, setDescription] = useState(currentProject?.product_description || '')

    return (
        <div className="space-y-4 max-w-160">
            <LemonTextArea
                id="product-description-textarea" // Slightly dirty ID for .focus() elsewhere
                value={description}
                onChange={setDescription}
                disabled={currentProjectLoading}
                placeholder={`What's the essence of ${currentProject ? currentProject.name : 'your product'}?`}
                onPressCmdEnter={() => updateCurrentProject({ product_description: description })}
                maxLength={1000}
            />
            <LemonButton
                type="primary"
                onClick={() => updateCurrentProject({ product_description: description })}
                disabled={!currentProject || description === currentProject.product_description}
                loading={currentProjectLoading}
            >
                Save description
            </LemonButton>
        </div>
    )
}
