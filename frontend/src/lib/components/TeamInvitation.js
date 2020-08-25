import React from 'react'
import { Modal, Switch, Popconfirm } from 'antd'
import { CopyToClipboard } from 'lib/components/CopyToClipboard'
import { useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { InfoCircleOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'

export function TeamInvitationContent({ user }) {
    const { userUpdateRequest } = useActions(userLogic)
    const isSignupEnabled = Boolean(user.team.signup_token)

    return (
        <div>
            <p>
                <CopyToClipboard
                    data-attr="copy-invite-to-clipboard-input"
                    url={isSignupEnabled ? window.location.origin + '/signup/' + user.team.signup_token : null}
                    placeholder="disabled and revoked – switch on to generate a new link"
                    addonBefore="Team Invite Link"
                    addonAfter={
                        <Popconfirm
                            title="Revoke current link globally?"
                            okText="Revoke"
                            okType="danger"
                            icon={<InfoCircleOutlined style={{ color: red.primary }} />}
                            onConfirm={() => {
                                userUpdateRequest({ team: { signup_state: false } }, 'team.signup_state')
                            }}
                            disabled={!isSignupEnabled}
                        >
                            <Switch
                                size="small"
                                checked={isSignupEnabled}
                                onChange={() => {
                                    if (!isSignupEnabled)
                                        userUpdateRequest({ team: { signup_state: true } }, 'team.signup_state')
                                }}
                            />
                        </Popconfirm>
                    }
                />
            </p>
            Build an even better product <i>together</i>.
        </div>
    )
}

export function TeamInvitationModal({ user, visible, onCancel }) {
    return (
        <Modal visible={visible} footer={null} onCancel={onCancel}>
            <div data-attr="invite-team-modal">
                <h2>Invite Teammate</h2>
                <TeamInvitationContent user={user} />
            </div>
        </Modal>
    )
}
