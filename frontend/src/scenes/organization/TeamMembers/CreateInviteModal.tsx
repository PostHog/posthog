import React, { useState, useRef, useCallback } from 'react'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { invitesLogic } from './invitesLogic'
import { Input, Alert, Button, ButtonProps } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { isEmail } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'
import { UserAddOutlined } from '@ant-design/icons'

export function CreateInviteModalWithButton(buttonProps: ButtonProps): JSX.Element {
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
        if (emailRef.current) {
            emailRef.current.setValue('')
        }
    }, [setIsVisible, setErrorMessage])

    const handleSubmit = (): void => {
        setErrorMessage(null)
        const potentialEmail = emailRef.current?.state.value
        if (!potentialEmail?.length) {
            setErrorMessage('You must specify the email address for which this invite is intended.')
        } else if (!isEmail(potentialEmail)) {
            setErrorMessage('This does not look like a valid email address.')
        } else {
            createInvite({ targetEmail: potentialEmail })
            closeModal()
            if (location.pathname !== '/organization/members' && !user?.email_service_available) {
                push('/organization/members')
            }
        }
    }

    return (
        <>
            <Button
                type="primary"
                data-attr="invite-teammate-button"
                onClick={() => {
                    setIsVisible(true)
                }}
                icon={<UserAddOutlined />}
                {...buttonProps}
            >
                Invite Team Member
            </Button>
            <Modal
                title={`Inviting Team Member${user?.organization ? ' to ' + user?.organization?.name : ''}`}
                okText={user?.email_service_available ? 'Send Invite' : 'Create Invite Link'}
                cancelText="Cancel"
                onOk={handleSubmit}
                onCancel={closeModal}
                visible={isVisible}
            >
                <p>The invite will only work with the specified email address and will expire after 3 days.</p>
                <form
                    onSubmit={(e) => {
                        e.preventDefault()
                        handleSubmit()
                    }}
                    data-attr="invite-teammate-form"
                >
                    <div className="input-set">
                        <label htmlFor="invitee-email">Email address</label>
                        <Input
                            data-attr="invite-email-input"
                            ref={emailRef}
                            maxLength={254}
                            autoFocus
                            type="email"
                            name="invitee-email"
                        />
                    </div>
                </form>
                {errorMessage && <Alert message={errorMessage} type="error" style={{ marginBottom: '1rem' }} />}

                {!user?.email_service_available && (
                    <Alert
                        type="warning"
                        message={
                            <>
                                Sending emails is not enabled in your PostHog instance.
                                <br />
                                Remember to <b>share the invite link</b> with the team member you want to invite.
                            </>
                        }
                    />
                )}
            </Modal>
        </>
    )
}
