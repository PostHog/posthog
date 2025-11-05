import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { organizationLogic } from '../organizationLogic'

export function CreateEnvironmentModal({
    isVisible,
    onClose,
    inline = false,
}: {
    isVisible: boolean
    onClose?: () => void
    inline?: boolean
}): JSX.Element {
    const { currentProject } = useValues(projectLogic)
    const { currentTeamLoading } = useValues(teamLogic)
    const { createTeam } = useActions(teamLogic)
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
        createTeam({ name, is_demo: false })
        reportProjectCreationSubmitted(currentOrganization?.teams ? currentOrganization.teams.length : 0, name.length)
    }

    // Anytime the team changes close the modal as it indicates we have created a new team
    useEffect(() => {
        closeModal()
    }, [currentProject]) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <LemonModal
            width={560}
            title={currentProject ? `Create an environment within ${currentProject.name}` : 'Create a environment'}
            description={
                <p>
                    Use environments to keep your data completely separate, while sharing the setup (such as dashboards
                    or taxonomy). A common pattern is having separate production, staging, and development environments.
                    <br />
                    <Link to="https://posthog.com/docs/settings/projects" target="_blank" disableDocsPanel>
                        Learn more in PostHog docs.
                    </Link>
                </p>
            }
            footer={
                <>
                    {onClose && (
                        <LemonButton
                            type="secondary"
                            onClick={onClose}
                            disabledReason={currentTeamLoading ? 'Creating environment...' : undefined}
                        >
                            Cancel
                        </LemonButton>
                    )}
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={currentTeamLoading}
                        disabledReason={!name ? 'Think of a name!' : null}
                    >
                        Create environment
                    </LemonButton>
                </>
            }
            isOpen={isVisible}
            onClose={onClose}
            inline={inline}
            closable={!currentTeamLoading}
        >
            <LemonField.Pure label="Environment name">
                <LemonInput
                    placeholder="E.g. development"
                    maxLength={64}
                    autoFocus
                    value={name}
                    onChange={(value) => setName(value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            handleSubmit()
                        }
                    }}
                    disabled={currentTeamLoading}
                />
            </LemonField.Pure>
        </LemonModal>
    )
}
