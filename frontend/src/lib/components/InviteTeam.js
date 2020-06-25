import React from 'react'
import { CopyToClipboard } from 'lib/components/CopyToClipboard'

export function InviteTeam({ user }) {
    const url = window.location.origin
    return (
        <div data-attr="invite-team-modal">
            <br />
            Send your team the following URL:
            <br />
            <br />
            <div>
                <CopyToClipboard
                    data-attr="copy-invite-to-clipboard-input"
                    url={url + '/signup/' + user.team.signup_token}
                />
            </div>
            <br />
        </div>
    )
}
