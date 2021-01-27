import { Alert, Input, Modal } from 'antd'
import { useActions, useValues } from 'kea'
import React, { Dispatch, SetStateAction, useCallback, useRef, useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

export function CreateProjectModal({
    isVisible,
    setIsVisible,
    title,
    caption,
}: {
    isVisible: boolean
    setIsVisible?: Dispatch<SetStateAction<boolean>>
    title?: string
    caption?: JSX.Element
}): JSX.Element {
    const { createTeam } = useActions(teamLogic)
    const { user } = useValues(userLogic)
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
            onOk={() => {
                const name = inputRef.current?.state.value?.trim()
                if (name) {
                    setErrorMessage(null)
                    createTeam(name)
                    closeModal()
                } else {
                    setErrorMessage('Your project needs a name!')
                }
            }}
            okButtonProps={{
                'data-attr': 'create-project-ok',
            }}
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
                />
            </div>
            {errorMessage && <Alert message={errorMessage} type="error" style={{ marginTop: '1rem' }} />}
        </Modal>
    )
}
