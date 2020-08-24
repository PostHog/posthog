import React, { useState } from 'react'
import { Modal, Switch } from 'antd'
import { CopyToClipboard } from 'lib/components/CopyToClipboard'
import api from '../api'

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
    const signup_token_state = user['team']['signup_token']
    const signup_data = `{'team':{'signup_token': ${signup_token_state}}}`
    // TODO : Remove this console log statement
    console.log(signup_data)
    if (signup_token_state != null) {
        return (
            <div>
                <p>
                    <TeamInvitationLink user={user} />
                </p>
                Invite teammates with the link above.
                <br />
                Build an even better product, <i>together</i>.
                <br />
                Link Sharing: <Switch defaultChecked onChange={() => api.update(url, signup_data)} />
            </div>
        )
    } else {
        return (
            <div>
                Link Sharing: <Switch onChange={() => api.update(url, signup_data)} />
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
