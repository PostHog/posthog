import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useEffect, useState } from 'react'
import { projectLogic } from 'scenes/projectLogic'

import { organizationLogic } from '../organizationLogic'

export function CreateProjectModal({
    isVisible,
    onClose,
    inline = false,
}: {
    isVisible: boolean
    onClose?: () => void
    inline?: boolean
}): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { createProject } = useActions(projectLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { reportProjectCreationSubmitted } = useActions(eventUsageLogic)
    const [name, setName] = useState<string>('')

    const closeModal: () => void = () => {
        if (onClose) {
            onClose()
            if (name) {
                setName('')
            }
        }
    }
    const handleSubmit = (): void => {
        createProject({ name })
        reportProjectCreationSubmitted(currentOrganization?.teams ? currentOrganization.teams.length : 0, name.length)
    }

    // Anytime the team changes close the modal as it indicates we have created a new team
    useEffect(() => {
        closeModal()
    }, [currentProject])

    return (
        <LemonModal
            width={560}
            title={currentOrganization ? `Create a project within ${currentOrganization.name}` : 'Create a project'}
            description={
                <>
                    <p>
                        Use projects to organize your data into separate collections – for example, to create
                        separate environments for production / staging / local development.
                    </p>
                    <p>
                        <strong>Tip:</strong> We recommend using the same project for both your website and app to track
                        conversion fully.{' '}
                        <Link to="https://posthog.com/manual/organizations-and-projects#projects" target="_blank">
                            Learn more in PostHog Docs.
                        </Link>
                    </p>
                    {currentOrganization?.teams?.some((team) => team.name.toLowerCase() === 'default project') && (
                        <p>
                            <strong>Bonus tip:</strong> You can always rename your "Default project".
                        </p>
                    )}
                </>
            }
            footer={
                <>
                    {onClose && (
                        <LemonButton
                            type="secondary"
                            onClick={onClose}
                            disabledReason={currentProjectLoading ? 'Creating team...' : undefined}
                        >
                            Cancel
                        </LemonButton>
                    )}
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={currentProjectLoading}
                        disabledReason={!name ? 'Think of a name!' : null}
                    >
                        Create project
                    </LemonButton>
                </>
            }
            isOpen={isVisible}
            onClose={onClose}
            inline={inline}
            closable={!currentProjectLoading}
        >
            <LemonField.Pure label="Project name">
                <LemonInput
                    placeholder="Production / Staging / Admin App"
                    maxLength={64}
                    autoFocus
                    value={name}
                    onChange={(value) => setName(value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            handleSubmit()
                        }
                    }}
                    disabled={currentProjectLoading}
                />
            </LemonField.Pure>
        </LemonModal>
    )
}
