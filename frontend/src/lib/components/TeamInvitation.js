import React from 'react'
import { Modal } from 'antd'
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
    return (
        <div>
            <p>
                <TeamInvitationLink user={user} />
            </p>
            Invite teammates with the link above.
            <br />
            Build an even better product, <i>together</i>.
        </div>
    )
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
