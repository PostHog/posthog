import React from 'react'
import { Input, Button, Form, Select } from 'antd'
import { useActions } from 'kea'
import { slugify } from 'lib/utils'
import { SaveOutlined } from '@ant-design/icons'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'

export function NewDashboard({ dashboard, model }) {
    const [form] = Form.useForm()
    const { addDashboard } = useActions(model)

    return (
        <Form
            layout="vertical"
            form={form}
            initialValues={dashboard}
            onFinish={(values) => {
                addDashboard(values)
            }}
        >
            <Form.Item
                name="name"
                label="Dashboard name"
                className={rrwebBlockClass}
                rules={[{ required: true, message: 'Please give your dashboard a name.' }]}
            >
                <Input
                    autoFocus={true}
                    onChange={(e) => form.setFieldsValue({ key: slugify(e.target.value) })}
                    data-attr="dashboard-name"
                />
            </Form.Item>

            <Form.Item name="copyFromTemplate" label="Start from" className={rrwebBlockClass}>
                <Select data-attr="copyFromTemplate" style={{ width: '100%' }} defaultValue={''}>
                    <Select.Option value="">Empty Dashboard</Select.Option>
                    <Select.Option value="DEFAULT_APP">Default Dashboard - App</Select.Option>
                    <Select.Option value="DEFAULT_WEB">Default Dashboard - Web</Select.Option>
                </Select>
            </Form.Item>

            <br />

            <Form.Item>
                <Button icon={<SaveOutlined />} htmlType="submit" type="primary" data-attr="dashboard-submit">
                    Create
                </Button>
            </Form.Item>
        </Form>
    )
}
