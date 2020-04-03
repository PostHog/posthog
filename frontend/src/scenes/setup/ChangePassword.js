import React, { Component } from 'react'
import { toast } from 'react-toastify'
import api from '../../lib/api'

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
            await api.patch('todo', {
                oldPassword: this.state.oldPassword,
                newPassword: this.state.newPassword,
            })
            toast.success('Password changed')
        } catch {
            toast.error('Password change failed')
        } finally {
            this.setState({
                oldPassword: '',
                newPassword: '',
            })
        }
    }

    render() {
        return (
            <form id="change-password" onSubmit={this.save}>
                <label>Old Password</label>
                <input
                    name="oldPassword"
                    required
                    type="password"
                    className="form-control"
                    onChange={this.handleChange}
                    value={this.state.oldPassword}
                    style={{ maxWidth: 400 }}
                />
                <label>New Password</label>
                <input
                    name="newPassword"
                    required
                    type="password"
                    className="form-control"
                    onChange={this.handleChange}
                    value={this.state.newPassword}
                    style={{ maxWidth: 400 }}
                />
                <br />
                <button type="submit" className="btn btn-outline-primary">
                    Change Password
                </button>
            </form>
        )
    }
}
