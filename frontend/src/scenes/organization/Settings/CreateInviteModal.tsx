import React, { useState, useRef, useCallback } from 'react'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { invitesLogic } from './invitesLogic'
import { Input, Alert, Button, ButtonProps } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { isEmail } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'
import { UserAddOutlined } from '@ant-design/icons'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { urls } from 'scenes/urls'

export function CreateInviteModalWithButton(buttonProps: ButtonProps): JSX.Element {
    const { createInvite } = useActions(invitesLogic)
    const { push } = useActions(router)
    const { location } = useValues(router)
    const { preflight } = useValues(preflightLogic)
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
            if (location.pathname !== urls.organizationSettings() && !preflight?.email_service_available) {
                push(urls.organizationSettings())
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
                Invite team member
            </Button>
            <Modal
                title={`Inviting Team Member${user?.organization ? ' to ' + user?.organization?.name : ''}`}
                okText={preflight?.email_service_available ? 'Send Invite' : 'Create Invite Link'}
                cancelText="Cancel"
                onOk={handleSubmit}
                okButtonProps={{
                    // @ts-expect-error - data-attr works just fine despite not being in ButtonProps
                    'data-attr': 'invite-team-member-submit',
                    disabled: preflight?.licensed_users_available === 0,
                }}
                onCancel={closeModal}
                visible={isVisible}
            >
                {preflight?.licensed_users_available === 0 ? (
                    <Alert
                        type="warning"
                        showIcon
                        message={
                            <>
                                You've hit the limit of team members you can invite to your PostHog instance given your
                                license. Please contact <a href="mailto:sales@posthog.com">sales@posthog.com</a> to
                                upgrade your license.
                            </>
                        }
                    />
                ) : (
                    <form
                        onSubmit={(e) => {
                            e.preventDefault()
                            handleSubmit()
                        }}
                        data-attr="invite-teammate-form"
                    >
                        <p>The invite will only work with the specified email address and will expire after 3 days.</p>
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
                        {errorMessage && <Alert message={errorMessage} type="error" style={{ marginBottom: '1rem' }} />}

                        {!preflight?.email_service_available && (
                            <Alert
                                type="warning"
                                message={
                                    <>
                                        Sending emails is not enabled in your PostHog instance.
                                        <br />
                                        Remember to <b>share the invite link</b> with the team member you want to
                                        invite.
                                    </>
                                }
                            />
                        )}
                    </form>
                )}
            </Modal>
        </>
    )
}
