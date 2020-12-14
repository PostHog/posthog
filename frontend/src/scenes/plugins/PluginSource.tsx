import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Button, Form, Input } from 'antd'
import MonacoEditor from 'react-monaco-editor'
import { Drawer } from 'lib/components/Drawer'

const defaultSource = `// /* Runs on every event */
function processEvent(event, { config }) {
    // Some events (like $identify) don't have properties
    if (event.properties) {
        event.properties['hello'] = \`Hello \${config.name || 'world'}\`
    }
    
    // Return the event to injest, return nothing to discard  
    return event
}

// /* Ran whenever the plugin VM initialises */
// function setupPlugin (meta) {
// 
// }

// /* Ran once per hour on each worker instance */
// function runEveryHour(meta) {
//     const weather = await (await fetch('https://weather.example.api/?city=New+York')).json()
//     posthog.capture('weather', { degrees: weather.deg, fahrenheit: weather.us })
// }
`

const defaultConfig = [
    {
        markdown: 'Specify your config here',
    },
    {
        key: 'username',
        name: 'Person to greet',
        type: 'string',
        hint: 'Used to personalise the property `hello`',
        default: '',
        required: false,
        order: 2,
    },
]

export function PluginSource(): JSX.Element {
    const { editingPlugin, editingSource, loading } = useValues(pluginsLogic)
    const { setEditingSource, editPluginSource } = useActions(pluginsLogic)
    const [form] = Form.useForm()

    useEffect(() => {
        if (editingPlugin) {
            const newPlugin = !editingPlugin.source && Object.keys(editingPlugin.config_schema).length === 0
            form.setFieldsValue({
                name: editingPlugin.name || 'Untitled Plugin',
                source: newPlugin ? defaultSource : editingPlugin.source,
                configSchema: JSON.stringify(newPlugin ? defaultConfig : editingPlugin.config_schema, null, 2),
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
            title={`Coding Plugin: ${editingPlugin?.name}`}
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
                        <p>
                            <a href="https://posthog.com/docs/plugins/overview" target="_blank">
                                Read the documentation.
                            </a>
                        </p>
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
