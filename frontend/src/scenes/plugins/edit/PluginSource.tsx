import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Button, Form, Input } from 'antd'
import MonacoEditor from '@monaco-editor/react'
import { Drawer } from 'lib/components/Drawer'

// @ts-ignore
import SCAFFOLD_index from '!raw-loader!@posthog/plugin-scaffold/dist/index.d.ts'
// @ts-ignore
import SCAFFOLD_errors from '!raw-loader!@posthog/plugin-scaffold/dist/errors.d.ts'
// @ts-ignore
import SCAFFOLD_types from '!raw-loader!@posthog/plugin-scaffold/dist/types.d.ts'
import { validateJsonFormItem } from 'lib/utils'

const defaultSource = `// Learn more about plugins at: https://posthog.com/docs/plugins/build/overview

// Processes each event, optionally transforming it
export function processEvent(event, { config }) {
    // Some events (such as $identify) don't have properties
    if (event.properties) {
        event.properties['hello'] = \`Hello \${config.name}\`
    }
    // Return the event to be ingested, or return null to discard
    return event
}

// Runs when the plugin is loaded, allows for preparing it as needed
export function setupPlugin (meta) {
    console.log(\`The date is \${new Date().toDateString()}\`)
}

// Runs every hour on the hour
async function runEveryHour(meta) {
    const response = await fetch('https://palabras-aleatorias-public-api.herokuapp.com/random')
    const data = await response.json()
    const randomSpanishWord = data.body.Word
    console.log(\`¡\${randomSpanishWord.toUpperCase()}!\`)
}`

const defaultConfig = [
    {
        markdown: 'Specify your config here',
    },
    {
        key: 'name',
        name: 'Person to greet',
        type: 'string',
        hint: 'Used to personalise the property `hello`',
        default: 'world',
        required: false,
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
            onClose={() => {
                if (form.getFieldValue('source') !== editingPlugin?.source) {
                    confirm('You have unsaved changes in your plugin. Are you sure you want to exit?') &&
                        setEditingSource(false)
                } else {
                    setEditingSource(false)
                }
            }}
            width={'min(90vw, 64rem)'}
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
                            Read our{' '}
                            <a href="https://posthog.com/docs/plugins/build/overview" target="_blank">
                                plugin building overview in PostHog Docs
                            </a>{' '}
                            for a good grasp of possibilities.
                            <br />
                            Once satisfied with your plugin, feel free to{' '}
                            <a
                                href="https://posthog.com/docs/plugins/build/tutorial#submitting-your-plugin"
                                target="_blank"
                            >
                                submit it to the official Plugin Library
                            </a>
                            .
                        </p>
                        <Form.Item label="Name" name="name" required rules={[requiredRule]}>
                            <Input />
                        </Form.Item>
                        <Form.Item label="Source Code" name="source" required rules={[requiredRule]}>
                            <MonacoEditor
                                language="typescript"
                                theme="vs-dark"
                                height={400}
                                options={{
                                    minimap: { enabled: false },
                                }}
                                beforeMount={(monaco) => {
                                    monaco.languages.typescript.typescriptDefaults.addExtraLib(
                                        `declare module '@posthog/plugin-scaffold' { ${SCAFFOLD_index} }`,
                                        'file:///node_modules/@types/@posthog/plugin-scaffold/index.d.ts'
                                    )
                                    monaco.languages.typescript.typescriptDefaults.addExtraLib(
                                        `declare module '@posthog/plugin-scaffold' { ${SCAFFOLD_types} }`,
                                        'file:///node_modules/@types/@posthog/plugin-scaffold/types.d.ts'
                                    )
                                    monaco.languages.typescript.typescriptDefaults.addExtraLib(
                                        `declare module '@posthog/plugin-scaffold' { ${SCAFFOLD_errors} }`,
                                        'file:///node_modules/@types/@posthog/plugin-scaffold/errors.d.ts'
                                    )
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
                                    validator: validateJsonFormItem,
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
