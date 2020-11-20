import React, { useState } from 'react'
import { toast } from 'react-toastify'
import api from 'lib/api'
import { Input, Button } from 'antd'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import Form from 'antd/lib/form/Form'
import FormItem from 'antd/lib/form/FormItem'

export function ChangePassword(): JSX.Element {
    const { user } = useValues(userLogic)
    const { userUpdateSuccess } = useActions(userLogic)

    const [current_password, setCurrentPassword] = useState('')
    const [new_password, setNewPassword] = useState('')
    const [new_passwordRepeat, setNewPasswordRepeat] = useState('')

    async function submit(): Promise<void> {
        try {
            userUpdateSuccess(
                await api.update('api/users/@me/change_password', {
                    current_password: current_password,
                    new_password: new_password,
                    new_password_repeat: new_passwordRepeat,
                })
            )
            toast.success('Password changed!')
            setCurrentPassword('')
            setNewPassword('')
            setNewPasswordRepeat('')
        } catch (response) {
            toast.error(response.detail)
        }
    }

    return (
        <Form onFinish={submit} labelAlign="left" layout="vertical">
            <FormItem
                label="Current Password"
                rules={[
                    {
                        required: !user || user.has_password,
                        message: 'Please input current password!',
                    },
                ]}
            >
                <Input.Password
                    name="current_password"
                    required
                    onChange={(event) => {
                        setCurrentPassword(event.target.value)
                    }}
                    value={current_password}
                    style={{ maxWidth: 400 }}
                    autoComplete="current-password"
                    disabled={!!user && !user.has_password}
                    placeholder={user && !user.has_password ? 'signed up with external login' : undefined}
                />
            </FormItem>
            <FormItem
                label="New Password"
                rules={[
                    {
                        required: true,
                        message: 'Please input new password!',
                    },
                ]}
            >
                <Input.Password
                    name="new_password"
                    required
                    onChange={(event) => {
                        setNewPassword(event.target.value)
                    }}
                    value={new_password}
                    style={{ maxWidth: 400 }}
                    autoComplete="new-password"
                />
            </FormItem>
            <FormItem
                label="Repeat New Password"
                rules={[
                    {
                        required: true,
                        message: 'Please input new password twice!',
                    },
                ]}
            >
                <Input.Password
                    name="new_passwordRepeat"
                    required
                    onChange={(event) => {
                        setNewPasswordRepeat(event.target.value)
                    }}
                    value={new_passwordRepeat}
                    style={{ maxWidth: 400 }}
                    autoComplete="new-password"
                />
            </FormItem>
            <FormItem>
                <Button type="primary" htmlType="submit">
                    Change Password
                </Button>
            </FormItem>
        </Form>
    )
}
