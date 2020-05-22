import React, { Component } from 'react'
import { toast } from 'react-toastify'
import { Button, Tooltip, Input } from 'antd'
import { CopyOutlined } from '@ant-design/icons'

export class InviteTeam extends Component {
    urlRef = React.createRef()
    copyToClipboard = () => {
        this.urlRef.current.focus()
        this.urlRef.current.select()
        document.execCommand('copy')
        this.urlRef.current.blur()
        toast('Link copied!')
    }
    render() {
        let url = window.location.origin
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
                        ref={this.urlRef}
                        value={url + '/signup/' + this.props.user.team.signup_token}
                        suffix={
                            <Tooltip title="Copy to Clipboard">
                                <Button onClick={this.copyToClipboard} type="default" icon={<CopyOutlined />} />
                            </Tooltip>
                        }
                    />
                </div>
                <br />
            </div>
        )
    }
}
