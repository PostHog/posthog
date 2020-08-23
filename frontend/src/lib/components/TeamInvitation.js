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
    const url = window.location.origin
    const signup_data = signup_token => ({
        method: 'PATCH', // POST, PUT, DELETE, etc.
        headers: {
            team: { signup_token: signup_token },
            'Content-Type': 'application/json',
        },
    })
    console.log(user)
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
                Link Sharing: <Switch defaultChecked onChange={() => fetch(url, signup_data(false))} />
            </div>
        )
    } else {
        return (
            <div>
                Link Sharing: <Switch onChange={() => fetch(url, signup_data(true))} />
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
