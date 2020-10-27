import React, { useState, useRef, useCallback } from 'react'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { invitesLogic } from './logic'
import { Input, Alert, Button } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { isEmail } from 'lib/utils'

export function CreateOrgInviteModalWithButton(): JSX.Element {
    const { createInvite } = useActions(invitesLogic)
    const { push } = useActions(router)
    const { location } = useValues(router)

    const [isVisible, setIsVisible] = useState(false)
    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const emailRef = useRef<Input | null>(null)

    const closeModal: () => void = useCallback(() => {
        setErrorMessage(null)
        setIsVisible(false)
        if (emailRef.current) emailRef.current.setValue('')
    }, [setIsVisible, setErrorMessage])

    return (
        <>
            <Button
                type="primary"
                data-attr="invite-teammate-button"
                onClick={() => {
                    setIsVisible(true)
                }}
            >
                + Invite Teammate
            </Button>
            <Modal
                title="Inviting Teammate"
                okText="Create Invite"
                cancelText="Cancel"
                onOk={() => {
                    setErrorMessage(null)
                    const potentialEmail = emailRef.current?.state.value
                    if (!potentialEmail?.length) {
                        setErrorMessage('You must specify the email address this invite is intended for.')
                    } else if (!isEmail(potentialEmail)) {
                        setErrorMessage("This doesn't look like a valid email address.")
                    } else {
                        createInvite({ targetEmail: potentialEmail })
                        closeModal()
                        if (location.pathname !== '/organization/invites') push('/organization/invites')
                    }
                }}
                onCancel={closeModal}
                visible={isVisible}
            >
                <p>Create an invite for a teammate with a specific email address.</p>
                <Input
                    data-attr="invite-email-input"
                    addonBefore="Email address"
                    ref={emailRef}
                    maxLength={254}
                    type="email"
                />
                {errorMessage && <Alert message={errorMessage} type="error" style={{ marginTop: '1rem' }} />}
            </Modal>
        </>
    )
}
