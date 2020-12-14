import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Button, Form, Input } from 'antd'
import MonacoEditor from 'react-monaco-editor'
import { Drawer } from 'lib/components/Drawer'

const defaultCode = `// Write your plugin here!
function processEvent(event) {
    if (event.properties) {
        event.properties['changed'] = true
    }
    return event
}
`

export function PluginSource(): JSX.Element {
    const { editingPlugin, editingSource, loading } = useValues(pluginsLogic)
    const { setEditingSource, editPluginSource } = useActions(pluginsLogic)
    const [form] = Form.useForm()

    useEffect(() => {
        if (editingPlugin) {
            form.setFieldsValue({
                name: editingPlugin.name || '',
                source: editingPlugin.source || defaultCode,
                configSchema: JSON.stringify(editingPlugin.config_schema, null, 2),
            })
        } else {
            form.resetFields()
        }
    }, [editingPlugin?.id, editingSource])

    function savePluginSource(values: any): void {
        if (editingPlugin) {
            editPluginSource({ ...values, id: editingPlugin.id, configSchema: JSON.parse(values.configSchema) })
        }
    }

    const requiredRule = {
        required: true,
        message: 'Please enter a value!',
    }

    return (
        <Drawer
            forceRender={true}
            visible={editingSource}
            onClose={() => setEditingSource(false)}
            width={'min(90vw, 820px)'}
            title={`Edit Plugin: ${editingPlugin?.name}`}
            placement="left"
            footer={
                <div style={{ textAlign: 'right' }}>
                    <Button onClick={() => setEditingSource(false)} style={{ marginRight: 16 }}>
                        Cancel
                    </Button>
                    <Button type="primary" loading={loading} onClick={form.submit}>
                        Save
                    </Button>
                </div>
            }
        >
            <Form form={form} layout="vertical" onFinish={savePluginSource}>
                {editingSource ? (
                    <>
                        <Form.Item label="Name" name="name" required rules={[requiredRule]}>
                            <Input />
                        </Form.Item>
                        <Form.Item label="Source Code" name="source" required rules={[requiredRule]}>
                            <MonacoEditor
                                language="javascript"
                                theme="vs-dark"
                                height={400}
                                options={{
                                    minimap: { enabled: false },
                                }}
                            />
                        </Form.Item>
                        <Form.Item
                            label="Config Schema JSON"
                            name="configSchema"
                            required
                            rules={[
                                requiredRule,
                                {
                                    validator(_, value: string) {
                                        try {
                                            JSON.parse(value)
                                            return Promise.resolve()
                                        } catch (error) {
                                            return Promise.reject('Not valid JSON!')
                                        }
                                    },
                                },
                            ]}
                        >
                            <MonacoEditor language="json" theme="vs-dark" height={200} />
                        </Form.Item>
                    </>
                ) : null}
            </Form>
        </Drawer>
    )
}
