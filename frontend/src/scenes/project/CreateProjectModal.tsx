import { Alert, Input, Modal } from 'antd'
import { useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React, { useCallback, useRef, useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

export function CreateProjectModal({
    isVisible,
    setIsVisible,
    title,
    caption,
}: {
    isVisible: boolean
    setIsVisible?: (newValue: boolean) => void
    title?: string
    caption?: JSX.Element
}): JSX.Element {
    const { createTeam } = useActions(teamLogic)
    const { user } = useValues(userLogic)
    const { reportProjectCreationSubmitted } = useActions(eventUsageLogic)
    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const inputRef = useRef<Input | null>(null)

    const closeModal: () => void = useCallback(() => {
        if (setIsVisible) {
            setErrorMessage(null)
            setIsVisible(false)
            if (inputRef.current) {
                inputRef.current.setValue('')
            }
        }
    }, [inputRef, setIsVisible])

    const handleSubmit = (): void => {
        const name = inputRef.current?.state.value?.trim()
        if (name) {
            reportProjectCreationSubmitted(user?.organization?.teams ? user.organization.teams.length : 0, name.length)
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
            All organization members will be able to access the new project.
        </p>
    )

    return (
        <Modal
            title={
                title || (user?.organization ? `Creating a Project in ${user.organization.name}` : 'Creating a Project')
            }
            okText="Create Project"
            cancelButtonProps={setIsVisible ? undefined : { style: { display: 'none' } }}
            closable={!!setIsVisible}
            onOk={handleSubmit}
            onCancel={closeModal}
            visible={isVisible}
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
