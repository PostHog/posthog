import React from 'react'
import { CopyToClipboardInput } from 'lib/components/CopyToClipboard'
import { Modal, Switch, Popconfirm } from 'antd'
import { useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { InfoCircleOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'

export function TeamInvitationContent({ user, confirmRevocation = true }) {
    const { userUpdateRequest } = useActions(userLogic)
    const isSignupEnabled = Boolean(user.team.signup_token)
    const confirmChange = confirmRevocation && isSignupEnabled

    return (
        <div>
            <p>
                <CopyToClipboardInput
                    data-attr="copy-invite-to-clipboard-input"
                    value={isSignupEnabled ? window.location.origin + '/signup/' + user.team.signup_token : null}
                    description="link"
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
                            disabled={!confirmChange}
                        >
                            <Switch
                                size="small"
                                checked={isSignupEnabled}
                                onChange={() => {
                                    if (!confirmChange)
                                        userUpdateRequest(
                                            { team: { signup_state: !isSignupEnabled } },
                                            'team.signup_state'
                                        )
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
                <TeamInvitationContent
                    user={user}
                    confirmRevocation={false /* Popconfirm doesn't show up properly in Modal */}
                />
            </div>
        </Modal>
    )
}
