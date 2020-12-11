import React, { useEffect } from 'react'
import { useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Form, Input } from 'antd'

export function PluginSource(): JSX.Element {
    const { editingPlugin, editingSource } = useValues(pluginsLogic)
    const [form] = Form.useForm()

    console.log(editingPlugin)

    useEffect(() => {
        if (editingPlugin) {
            console.log('!!')
            form.setFieldsValue({
                name: editingPlugin.name,
                source: editingPlugin.source,
                configSchema: JSON.stringify(editingPlugin.config_schema, null, 2),
            })
        } else {
            form.resetFields()
        }
    }, [editingPlugin?.id, editingSource])

    function savePluginSource(values: any): void {
        console.log(values)
    }

    const requiredRule = {
        required: true,
        message: 'Please enter a value!',
    }

    return (
        <>
            <Form form={form} layout="vertical" onFinish={savePluginSource}>
                <Form.Item label="Name" name="name" required rules={[requiredRule]}>
                    <Input />
                </Form.Item>
                <Form.Item
                    label="Source Code"
                    extra="Write all the JavaScript here!"
                    name="source"
                    required
                    rules={[requiredRule]}
                >
                    <Input.TextArea autoSize />
                </Form.Item>
                <Form.Item label="Config Schema JSON" name="configSchema" required rules={[requiredRule]}>
                    <Input.TextArea autoSize />
                </Form.Item>
            </Form>
        </>
    )
}
