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
            <div>
                <br />
                Send your team the following URL:
                <br />
                <br />
                <div>
                    <Input
                        type="text"
                        ref={this.urlRef}
                        value={url + '/signup/' + this.props.user.team.signup_token}
                        disabled={true}
                        suffix={
                            <Tooltip title="Copy to Clipboard">
                                <Button
                                    onClick={this.copyToClipboard.bind(this)}
                                    type="default"
                                    icon={<CopyOutlined />}
                                />
                            </Tooltip>
                        }
                    />
                </div>
                <br />
            </div>
        )
    }
}
