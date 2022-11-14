import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PureField } from 'lib/forms/Field'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useCallback, useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'
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
    const { createTeam } = useActions(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { reportProjectCreationSubmitted } = useActions(eventUsageLogic)
    const [name, setName] = useState<string>('')

    const closeModal: () => void = useCallback(() => {
        if (onClose) {
            onClose()
            if (name) {
                setName('')
            }
        }
    }, [name, onClose])

    const handleSubmit = (): void => {
        createTeam(name)
        reportProjectCreationSubmitted(currentOrganization?.teams ? currentOrganization.teams.length : 0, name.length)
        closeModal()
    }

    return (
        <LemonModal
            title={currentOrganization ? `Create a project in ${currentOrganization.name}` : 'Create a project'}
            description={
                <p>
                    Safely silo data by using multiple projects.{' '}
                    <Link to="https://posthog.com/manual/organizations-and-projects#projects" target="_blank">
                        Learn more in Docs.
                    </Link>
                </p>
            }
            footer={
                <>
                    {onClose && (
                        <LemonButton type="secondary" onClick={() => onClose()}>
                            Cancel
                        </LemonButton>
                    )}
                    <LemonButton type="primary" onClick={() => handleSubmit()} disabled={!name}>
                        Create project
                    </LemonButton>
                </>
            }
            isOpen={isVisible}
            onClose={onClose}
            inline={inline}
        >
            <PureField label="Project name">
                <LemonInput
                    placeholder="The Next Big Thing"
                    maxLength={64}
                    autoFocus
                    value={name}
                    onChange={(value) => setName(value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            handleSubmit()
                        }
                    }}
                />
            </PureField>
        </LemonModal>
    )
}
