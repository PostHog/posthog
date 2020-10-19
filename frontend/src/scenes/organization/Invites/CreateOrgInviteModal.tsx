import React, { Dispatch, SetStateAction, useState, useRef, useCallback } from 'react'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { invitesLogic, InviteCreationMode } from './logic'
import { Input, Alert, Tabs, InputNumber } from 'antd'
import Modal from 'antd/lib/modal/Modal'

export function CreateOrgInviteModal({
    isVisible,
    setIsVisible,
}: {
    isVisible: boolean
    setIsVisible: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { createInvite } = useActions(invitesLogic)
    const { push } = useActions(router)
    const { location } = useValues(router)

    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const [currentMode, setCurrentMode] = useState<InviteCreationMode>('wildcard')
    const [maxUses, setMaxUses] = useState<number>(3)
    const emailRef = useRef<Input | null>(null)

    const closeModal: () => void = useCallback(() => {
        setErrorMessage(null)
        setIsVisible(false)
        if (emailRef.current) emailRef.current.setValue('')
    }, [setIsVisible])

    return (
        <Modal
            title="Creating an Organization Invite"
            okText="Create Invite"
            cancelText="Cancel"
            onOk={() => {
                setErrorMessage(null)
                createInvite({ mode: currentMode, maxUses, targetEmail: emailRef.current?.state.value })
                closeModal()
                if (location.pathname !== '/organization/invites') push('/organization/invites')
            }}
            onCancel={closeModal}
            visible={isVisible}
        >
            <Tabs
                size="small"
                activeKey={currentMode}
                onTabClick={(key: string) => {
                    setCurrentMode(key as InviteCreationMode)
                }}
            >
                <Tabs.TabPane key="wildcard" tab="Wildcard">
                    No restrictions on invited users. Be careful with this!
                </Tabs.TabPane>
                <Tabs.TabPane key="limited" tab="Limited number of uses">
                    Invite will become invalid after it's used{' '}
                    <InputNumber
                        onChange={(value) => {
                            setMaxUses(value as number)
                        }}
                        min={1}
                        value={maxUses}
                    />{' '}
                    {maxUses === 1 ? 'time' : 'times'}.
                </Tabs.TabPane>
                <Tabs.TabPane key="email" tab="Target email address">
                    <p>
                        Allow only user with the specified email address to use the invite.
                        <br />
                        Double-check for typos!
                    </p>

                    <Input addonBefore="Email address" ref={emailRef} maxLength={254} type="email" />
                </Tabs.TabPane>
            </Tabs>
            {errorMessage && <Alert message={errorMessage} type="error" style={{ marginBottom: '1rem' }} />}
        </Modal>
    )
}
