import React from 'react'
import { Input, Button, Form, Select } from 'antd'
import { useActions } from 'kea'
import { slugify } from 'lib/utils'
import { SaveOutlined } from '@ant-design/icons'

import { dashboardsModel } from '~/models/dashboardsModel'

export function NewDashboard(): JSX.Element {
    const [form] = Form.useForm()
    const { addDashboard } = useActions(dashboardsModel)

    return (
        <Form
            layout="vertical"
            form={form}
            onFinish={(values) => {
                addDashboard(values)
            }}
        >
            <Form.Item
                name="name"
                label="Dashboard name"
                className="ph-no-capture"
                rules={[{ required: true, message: 'Please give your dashboard a name.' }]}
            >
                <Input
                    autoFocus={true}
                    onChange={(e) => form.setFieldsValue({ key: slugify(e.target.value) })}
                    data-attr="dashboard-name-input"
                />
            </Form.Item>

            <Form.Item name="useTemplate" label="Start from" className="ph-no-capture">
                <Select data-attr="copy-from-template" style={{ width: '100%' }}>
                    <Select.Option data-attr="dashboard-select-empty" value="">
                        Empty Dashboard
                    </Select.Option>
                    <Select.Option data-attr="dashboard-select-default-app" value="DEFAULT_APP">
                        Default Dashboard - Web App
                    </Select.Option>
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
