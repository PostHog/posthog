import React from 'react'
import { Input, Button, Form } from 'antd'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { PasswordInput } from 'scenes/authentication/PasswordInput'

export function ChangePassword(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const [form] = Form.useForm()

    const updateCompleted = (): void => {
        form.resetFields()
    }

    return (
        <Form
            onFinish={(values) => updateUser(values, updateCompleted)}
            labelAlign="left"
            layout="vertical"
            requiredMark={false}
            form={form}
        >
            <Form.Item
                label="Current Password"
                rules={[
                    {
                        required: !user || user.has_password,
                        message: 'Please input your current password',
                    },
                ]}
                name="current_password"
            >
                <Input.Password
                    style={{ maxWidth: 400 }}
                    autoComplete="current-password"
                    disabled={(!!user && !user.has_password) || userLoading}
                    placeholder={user && !user.has_password ? 'signed up with external login' : '********'}
                    className="ph-ignore-input"
                />
            </Form.Item>
            <PasswordInput label="New Password" showStrengthIndicator style={{ maxWidth: 400 }} validateMinLength />
            <Form.Item>
                <Button type="primary" htmlType="submit" loading={userLoading}>
                    Change Password
                </Button>
            </Form.Item>
        </Form>
    )
}
