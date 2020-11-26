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
            if (location.pathname !== '/organization/invites' && !user?.email_service_available) {
                push('/organization/invites')
            }
        }
    }

    return (
        <>
            {type === 'text' ? (
                <span
                    onClick={() => {
                        setIsVisible(true)
                    }}
                >
                    Invite Teammate
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
                        Invite Teammate
                    </Button>
                </div>
            )}

            <Modal
                title="Inviting Teammate"
                okText={user?.email_service_available ? 'Send Invite' : 'Create Invite Link'}
                cancelText="Cancel"
                onOk={handleSubmit}
                onCancel={closeModal}
                visible={isVisible}
            >
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
                    <div>
                        Emails are not enabled in your PostHog instance.
                        <br />
                        Remember to <b>share the invite link</b> with the team member you want to invite.
                    </div>
                )}
            </Modal>
        </>
    )
}
