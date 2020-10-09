import React from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Form, Input, Modal, Switch } from 'antd'

export function PluginConfig(): JSX.Element {
    const { editingPlugin, pluginsLoading } = useValues(pluginsLogic)
    const { editPlugin, saveEditedPlugin } = useActions(pluginsLogic)
    const [form] = Form.useForm()

    return (
        <Modal
            visible={!!editingPlugin}
            onCancel={() => {
                editPlugin(null)
                form.resetFields()
            }}
            okText="Save"
            onOk={() => form.submit()}
            confirmLoading={pluginsLoading}
        >
            {editingPlugin ? (
                <div>
                    <h2>{editingPlugin.name}</h2>
                    <p>{editingPlugin.description}</p>

                    <Form
                        form={form}
                        layout="vertical"
                        name="basic"
                        initialValues={{ ...(editingPlugin.config || {}), __enabled: editingPlugin.enabled }}
                        onFinish={saveEditedPlugin}
                    >
                        <Form.Item label="Enabled?" name="__enabled" valuePropName="checked">
                            <Switch />
                        </Form.Item>
                        {Object.keys(editingPlugin.configSchema).map((configKey) => (
                            <Form.Item key={configKey} label={configKey} name={configKey}>
                                <Input />
                            </Form.Item>
                        ))}
                    </Form>
                </div>
            ) : null}
        </Modal>
    )
}
