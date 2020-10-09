import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Form, Input, Modal, Switch } from 'antd'

export function PluginModal(): JSX.Element {
    const { editingPlugin, pluginsLoading } = useValues(pluginsLogic)
    const { editPlugin, saveEditedPlugin } = useActions(pluginsLogic)
    const [form] = Form.useForm()

    useEffect(() => {
        if (editingPlugin) {
            form.setFieldsValue({ ...(editingPlugin.config || {}), __enabled: editingPlugin.enabled })
        } else {
            form.resetFields()
        }
    }, [editingPlugin?.name])

    return (
        <Modal
            forceRender={true}
            visible={!!editingPlugin}
            okText="Save"
            onOk={() => form.submit()}
            onCancel={() => editPlugin(null)}
            confirmLoading={pluginsLoading}
        >
            <Form form={form} layout="vertical" name="basic" onFinish={saveEditedPlugin}>
                {editingPlugin ? (
                    <div>
                        <h2>{editingPlugin.name}</h2>
                        <p>{editingPlugin.description}</p>

                        <Form.Item label="Enabled?" fieldKey="__enabled" name="__enabled" valuePropName="checked">
                            <Switch />
                        </Form.Item>
                        {Object.keys(editingPlugin.configSchema).map((configKey) => (
                            <Form.Item key={configKey} label={configKey} name={configKey}>
                                <Input />
                            </Form.Item>
                        ))}
                    </div>
                ) : null}
            </Form>
        </Modal>
    )
}
