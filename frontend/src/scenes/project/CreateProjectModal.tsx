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
            title={currentOrganization ? `Create a project in ${currentOrganization.name}` : 'Create a project'}
            description={
                <>
                    <p>For most companies, we recommend using 3 projects:</p>
                    <ol className={'mt-2'}>
                        <li>Local Development</li>
                        <li>Staging</li>
                        <li>Production</li>
                    </ol>
                    <p>
                        <strong>Tip:</strong> we recommend using the same project for both your website and app to track
                        across them. You can always apply a filter to focus on just one. Read the{' '}
                        <Link to="https://posthog.com/manual/organizations-and-projects#projects" target="_blank">
                            project docs{' '}
                        </Link>
                        for more information.
                    </p>
                    <p>
                        <strong>Bonus tip:</strong> you can rename your "Default Project" to "Production".
                    </p>
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
                    placeholder="Production / Staging / Local Development"
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
