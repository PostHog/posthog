import React, { useState } from 'react'
import { Modal, Switch } from 'antd'
import { CopyToClipboard } from 'lib/components/CopyToClipboard'

export function TeamInvitationLink({ user }) {
    return (
        <CopyToClipboard
            data-attr="copy-invite-to-clipboard-input"
            url={window.location.origin + '/signup/' + user.team.signup_token}
        />
    )
}

export function TeamInvitationContent({ user }) {
    const [linkSharingEnabled, setLinkState] = useState(true)
    if (user['team']['signup_token'] != null) {
        return (
            <div>
                <p>
                    <TeamInvitationLink user={user} />
                </p>
                Invite teammates with the link above.
                <br />
                Build an even better product, <i>together</i>.
                <br />
                Link Sharing: <Switch defaultChecked onChange={() => setLinkState(!linkSharingEnabled)} />
            </div>
        )
    } else {
        return (
            <div>
                Link Sharing: <Switch onChange={() => setLinkState(!linkSharingEnabled)} />
            </div>
        )
    }
}

export function TeamInvitationModal({ user, visible, onCancel }) {
    return (
        <Modal visible={visible} footer={null} onCancel={onCancel}>
            <div data-attr="invite-team-modal">
                <h2>Team Invitation</h2>
                <TeamInvitationContent user={user} />
            </div>
        </Modal>
    )
}
