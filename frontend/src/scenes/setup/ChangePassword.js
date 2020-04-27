import React, { Component } from 'react'
import { toast } from 'react-toastify'
import api from '../../lib/api'
import { Input, Button } from 'antd'

export class ChangePassword extends Component {
    constructor(props) {
        super(props)
        this.state = {
            oldPassword: '',
            newPassword: '',
        }
    }

    handleChange = event => {
        this.setState({
            [event.target.name]: event.target.value,
        })
    }

    save = async event => {
        event.preventDefault()
        try {
            await api.update('api/user/change_password', {
                oldPassword: this.state.oldPassword,
                newPassword: this.state.newPassword,
            })
            toast.success('Password changed')
        } catch (response) {
            toast.error(response.error)
        } finally {
            this.setState({
                oldPassword: '',
                newPassword: '',
            })
        }
    }

    render() {
        return (
            <div>
                <label>Old Password</label>
                <br />
                <Input.Password
                    name="oldPassword"
                    required
                    onChange={this.handleChange}
                    value={this.state.oldPassword}
                    style={{ maxWidth: 400 }}
                />
                <br />
                <label>New Password</label>
                <br />
                <Input.Password
                    name="newPassword"
                    required
                    onChange={this.handleChange}
                    value={this.state.newPassword}
                    style={{ maxWidth: 400 }}
                />
                <br />
                <br />
                <Button
                    type="primary"
                    onClick={e => {
                        e.preventDefault()
                        this.save()
                    }}
                >
                    Change Password
                </Button>
            </div>
        )
    }
}
