import React, { useEffect } from 'react'
import { Input, Form } from 'antd'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonButton } from 'lib/components/LemonButton'

export function UserDetails(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const [form] = Form.useForm()

    useEffect(() => {
        form.setFieldsValue({
            first_name: user?.first_name,
        })
    }, [user?.first_name])

    return (
        <Form
            onFinish={(values) => updateUser(values)}
            labelAlign="left"
            layout="vertical"
            requiredMark={false}
            form={form}
            style={{
                maxWidth: 400,
            }}
        >
            <Form.Item
                name="first_name"
                label="Your name"
                rules={[
                    {
                        required: true,
                        message: 'Please enter your name',
                    },
                    {
                        max: 150,
                        message: 'The name you have given is too long. Please pick something shorter.',
                    },
                ]}
            >
                <Input
                    className="ph-ignore-input"
                    autoFocus
                    data-attr="settings-update-first-name"
                    placeholder="Jane Doe"
                    disabled={userLoading}
                />
            </Form.Item>

            <Form.Item>
                <LemonButton type="primary" htmlType="submit" loading={userLoading}>
                    Update Details
                </LemonButton>
            </Form.Item>
        </Form>
    )
}
