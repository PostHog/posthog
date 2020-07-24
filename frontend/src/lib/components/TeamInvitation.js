import React, { useRef, useCallback } from 'react'
import { toast } from 'react-toastify'
import { Tooltip, Modal, Input } from 'antd'
import { CopyOutlined } from '@ant-design/icons'

export function TeamInvitationLink({ user }) {
    const url = window.location.origin

    const inputRef = useRef()

    const copyToClipboard = useCallback(() => {
        inputRef.current.focus()
        inputRef.current.select()
        document.execCommand('copy')
        inputRef.current.blur()
        toast('Team invitation link copied!')
    }, [inputRef])

    return (
        <Input
            data-attr="copy-invite-to-clipboard-input"
            type="text"
            ref={inputRef}
            value={url + '/signup/' + user.team.signup_token}
            suffix={
                <Tooltip title="Copy to clipboard">
                    <CopyOutlined onClick={copyToClipboard} />
                </Tooltip>
            }
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
