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
    const { loadUser } = useActions(userLogic)

    const [currentPassword, setCurrentPassword] = useState('')
    const [newPassword, setNewPassword] = useState('')

    async function submit(): Promise<void> {
        try {
            await api.update('api/user/change_password', {
                currentPassword,
                newPassword,
            })
            loadUser()
            toast.success('Password changed')
        } catch (response) {
            toast.error(response.error)
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
                    name="currentPassword"
                    required
                    onChange={(event) => {
                        setCurrentPassword(event.target.value)
                    }}
                    value={currentPassword}
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
                    name="newPassword"
                    required
                    onChange={(event) => {
                        setNewPassword(event.target.value)
                    }}
                    value={newPassword}
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
