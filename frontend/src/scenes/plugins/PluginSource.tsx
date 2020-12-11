import React, { useEffect } from 'react'
import { useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Form, Input } from 'antd'
import MonacoEditor from 'react-monaco-editor'

const defaultCode = `// Write your plugin here!
function processEvent(event) {
    if (event.properties) {
        event.properties['changed'] = true
    }
}
`

export function PluginSource(): JSX.Element {
    const { editingPlugin, editingSource } = useValues(pluginsLogic)
    const [form] = Form.useForm()

    console.log(editingPlugin)

    useEffect(() => {
        if (editingPlugin) {
            console.log('!!')
            form.setFieldsValue({
                name: editingPlugin.name,
                source: editingPlugin.source || defaultCode,
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
                <Form.Item label="Source Code" name="source" required rules={[requiredRule]}>
                    <MonacoEditor language="javascript" theme="vs-dark" height={600} />
                </Form.Item>
                <Form.Item label="Config Schema JSON" name="configSchema" required rules={[requiredRule]}>
                    <MonacoEditor language="json" theme="vs-dark" height={200} />
                </Form.Item>
            </Form>
        </>
    )
}
