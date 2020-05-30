import React, { useRef } from 'react'
import { toast } from 'react-toastify'
import { Button, Tooltip, Input } from 'antd'
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
            <br />
            Send your team the following URL:
            <br />
            <br />
            <div>
                <Input
                    data-attr="copy-invite-to-clipboard-input"
                    type="text"
                    ref={urlRef}
                    value={url + '/signup/' + user.team.signup_token}
                    suffix={
                        <Tooltip title="Copy to Clipboard">
                            <Button onClick={copyToClipboard} type="default" icon={<CopyOutlined />} />
                        </Tooltip>
                    }
                />
            </div>
            <br />
        </div>
    )
}
