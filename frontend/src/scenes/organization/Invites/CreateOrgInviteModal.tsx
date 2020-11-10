import React, { useState, useRef, useCallback } from 'react'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { invitesLogic } from './logic'
import { Input, Alert, Button } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { isEmail } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'
import { PlusOutlined } from '@ant-design/icons'

export function CreateOrgInviteModalWithButton({ type = 'button' }: { type?: 'button' | 'text' }): JSX.Element {
    const { createInvite } = useActions(invitesLogic)
    const { push } = useActions(router)
    const { location } = useValues(router)
    const { user } = useValues(userLogic)

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
            {type === 'text' ? (
                <span
                    onClick={() => {
                        setIsVisible(true)
                    }}
                >
                    Invite Team Member
                </span>
            ) : (
                <div className="mb text-right">
                    <Button
                        type="primary"
                        data-attr="invite-teammate-button"
                        onClick={() => {
                            setIsVisible(true)
                        }}
                        icon={<PlusOutlined />}
                    >
                        Invite Team Member
                    </Button>
                </div>
            )}

            <Modal
                title="Inviting Team member"
                okText="Create Invite Link"
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
                <p>
                    {user?.are_invite_emails_available ? (
                        "Your teammate will be able to join from the email they'll receive."
                    ) : (
                        <>
                            We'll create an invite link for your teammate. <b>Share it</b> with them so they're able to
                            join you.
                        </>
                    )}
                    Create an invite link for a team member with a specific email address.
                </p>
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
