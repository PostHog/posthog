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
        createTeam({ name, is_demo: false })
        reportProjectCreationSubmitted(currentOrganization?.teams ? currentOrganization.teams.length : 0, name.length)
        closeModal()
    }

    return (
        <LemonModal
            title={currentOrganization ? `Create a project within ${currentOrganization.name}` : 'Create a project'}
            description={
                <>
                    <p>
                        Use Projects to organize your data into separate collections. A project usually means
                        a completely distinct product, or an environment (production, staging, development).
                    </p>
                    <p>
                        <strong>Tip:</strong> We recommend using the same project for both your website and app to track
                        conversion fully.{' '}
                        <Link to="https://posthog.com/manual/organizations-and-projects#projects" target="_blank">
                            Learn more in Docs.
                        </Link>
                    </p>
                    {currentOrganization?.teams?.some((team) => team.name === 'Default Project') && (
                        <p>
                            <strong>Bonus tip:</strong> You can always rename your "Default Project".
                        </p>
                    )}
                </>
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
