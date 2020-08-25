import React from 'react'
import { Modal, Switch } from 'antd'
import { CopyToClipboard } from 'lib/components/CopyToClipboard'
import { useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'

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
                        <Switch
                            style={{ lineHeight: 0 }}
                            size="small"
                            checked={isSignupEnabled}
                            onChange={() => {
                                userUpdateRequest({ team: { signup_state: !isSignupEnabled } }, 'team.signup_state')
                            }}
                        />
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
