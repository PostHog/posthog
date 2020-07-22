import React, { useRef } from 'react'
import { toast } from 'react-toastify'
import { Tooltip, Input } from 'antd'
import { CopyOutlined } from '@ant-design/icons'

export function InviteTeam({ user }) {
    const urlRef = useRef()

    function copyToClipboard() {
        urlRef.current.focus()
        urlRef.current.select()
        document.execCommand('copy')
        urlRef.current.blur()
        toast('Link copied!')
    }

    const url = window.location.origin
    return (
        <div data-attr="invite-team-modal">
            <h2>Team Invite Link</h2>
            <p>
                Build an even better product, <i>together</i>.
            </p>
            <div>
                <Input
                    data-attr="copy-invite-to-clipboard-input"
                    type="text"
                    ref={urlRef}
                    value={url + '/signup/' + user.team.signup_token}
                    suffix={
                        <Tooltip title="Copy to Clipboard">
                            <CopyOutlined onClick={copyToClipboard} />
                        </Tooltip>
                    }
                />
            </div>
            <br />
        </div>
    )
}
