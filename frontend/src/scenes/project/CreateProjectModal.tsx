import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { projectLogic } from 'scenes/projectLogic'

import { organizationLogic } from '../organizationLogic'

const MOCK_PRODUCT_NAMES = [
    'Lemonify',
    'Pineapplify',
    'Bananify',
    'Mangofy',
    'Peachify',
    'Plumify',
    'Cherryfy',
    'Raspberryfy',
]

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
        reportProjectCreationSubmitted(
            currentOrganization?.projects ? currentOrganization.projects.length : 0,
            name.length
        )
    }

    // Anytime the project changes close the modal as it indicates we have created a new project
    useEffect(() => {
        closeModal()
    }, [currentProject]) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <LemonModal
            width={560}
            title={currentOrganization ? `Create a project within ${currentOrganization.name}` : 'Create a project'}
            description={
                <>
                    <p>
                        Use projects to isolate products that share nothing at all. Both data and setup (such as
                        dashboards or taxonomy) is separate between projects.
                    </p>
                    <p>
                        <strong>Tip:</strong> We recommend using the same project for both your website and app to track
                        conversion fully.{' '}
                        <Link to="https://posthog.com/docs/settings/projects" target="_blank" disableDocsPanel>
                            Learn more in PostHog docs.
                        </Link>
                    </p>
                    {currentOrganization?.projects?.some(
                        (project) => project.name.toLowerCase() === 'default project'
                    ) && (
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
                            disabledReason={currentProjectLoading ? 'Creating project...' : undefined}
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
                    placeholder={`E.g. ${MOCK_PRODUCT_NAMES[Math.floor(Math.random() * MOCK_PRODUCT_NAMES.length)]}`}
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
