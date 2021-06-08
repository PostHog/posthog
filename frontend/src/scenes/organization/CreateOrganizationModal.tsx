import { Alert, Input } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { useActions, useValues } from 'kea'
import React, { Dispatch, SetStateAction, useCallback, useRef, useState } from 'react'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from '../PreflightCheck/logic'

export function CreateOrganizationModal({
    isVisible,
    setIsVisible,
}: {
    isVisible: boolean
    setIsVisible?: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { createOrganization } = useActions(organizationLogic)
    const { organizationCreationAllowed } = useValues(preflightLogic)
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

    if (!organizationCreationAllowed) {
        return (
            <Modal title="Creating an Organization" closable={false} visible={isVisible} footer={null}>
                <Alert
                    type="error"
                    message={
                        <>
                            No more organizations can be created in this PostHog instance.
                            <br />
                            If you don't belong to a organization, you'll need to ask for an invite.
                        </>
                    }
                />
            </Modal>
        )
    }

    return (
        <Modal
            title="Creating an Organization"
            okText="Create Organization"
            cancelButtonProps={setIsVisible ? undefined : { style: { display: 'none' } }}
            closable={!!setIsVisible}
            onOk={() => {
                const name = inputRef.current?.state.value?.trim()
                if (name) {
                    setErrorMessage(null)
                    createOrganization(name)
                    closeModal()
                } else {
                    setErrorMessage('Your organization needs a name!')
                }
            }}
            okButtonProps={{
                // @ts-expect-error - data-attr works just fine despite not being in ButtonProps
                'data-attr': 'create-organization-ok',
            }}
            onCancel={closeModal}
            visible={isVisible}
        >
            <p>Organizations gather people building products together.</p>
            <Input
                addonBefore="Name"
                ref={inputRef}
                placeholder='for example "Acme Corporation"'
                maxLength={64}
                autoFocus
            />
            {errorMessage && <Alert message={errorMessage} type="error" style={{ marginTop: '1rem' }} />}
        </Modal>
    )
}
