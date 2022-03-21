import { Alert, Input, Modal } from 'antd'
import { useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React, { useCallback, useRef, useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { organizationLogic } from '../organizationLogic'

export function CreateProjectModal({
    isVisible,
    onClose,
    title,
    caption,
    mask,
}: {
    isVisible: boolean
    onClose?: () => void
    title?: string
    caption?: JSX.Element
    mask?: boolean
}): JSX.Element {
    const { createTeam } = useActions(teamLogic)
    const { currentOrganization, isProjectCreationForbidden } = useValues(organizationLogic)
    const { reportProjectCreationSubmitted } = useActions(eventUsageLogic)
    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const inputRef = useRef<Input | null>(null)

    const closeModal: () => void = useCallback(() => {
        if (onClose) {
            setErrorMessage(null)
            onClose()
            if (inputRef.current) {
                inputRef.current.setValue('')
            }
        }
    }, [inputRef, onClose])

    const handleSubmit = (): void => {
        const name = inputRef.current?.state.value?.trim()
        if (name) {
            reportProjectCreationSubmitted(
                currentOrganization?.teams ? currentOrganization.teams.length : 0,
                name.length
            )
            setErrorMessage(null)
            createTeam(name)
            closeModal()
        } else {
            setErrorMessage('Your project needs a name!')
        }
    }

    const defaultCaption = (
        <p>
            Projects are a way of tracking multiple products under the umbrella of a single organization.
            <br />
            All organization members will be able to access the new project upon creation, but you can make it private
            in its settings to restrict access.
            <br />
            <a href="https://posthog.com/docs/user-guides/organizations-and-projects" target="_blank" rel="noopener">
                Learn more about projects in Docs.
            </a>
        </p>
    )

    return isProjectCreationForbidden ? (
        <Modal
            title={
                currentOrganization
                    ? `You cannot create a project in ${currentOrganization.name}`
                    : 'You cannot create a project'
            }
            okButtonProps={onClose ? undefined : { style: { display: 'none' } }}
            onCancel={closeModal}
            visible={isVisible}
            mask={mask}
            wrapProps={isVisible && !mask ? { style: { pointerEvents: 'none' } } : undefined}
            closeIcon={null}
        >
            Your organization access level is insufficient for creating a new project.
            <br />
            Project creation requires administrator access.
        </Modal>
    ) : (
        <Modal
            title={
                title ||
                (currentOrganization ? `Creating a project in ${currentOrganization.name}` : 'Creating a project')
            }
            okText="Create project"
            cancelButtonProps={onClose ? undefined : { style: { display: 'none' } }}
            onOk={handleSubmit}
            onCancel={closeModal}
            visible={isVisible}
            mask={mask}
            wrapProps={isVisible && !mask ? { style: { pointerEvents: 'none' } } : undefined}
            closeIcon={null}
        >
            {caption || defaultCaption}
            <div className="input-set">
                <label htmlFor="projectName">Project Name</label>
                <Input
                    ref={inputRef}
                    placeholder='for example "Web app", "Mobile app", "Production", "Landing website"'
                    maxLength={64}
                    autoFocus
                    name="projectName"
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            handleSubmit()
                        }
                    }}
                />
            </div>
            {errorMessage && <Alert message={errorMessage} type="error" />}
        </Modal>
    )
}
