import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Button, Form, Input, Modal, Popconfirm, Switch } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'

export function PluginModal(): JSX.Element {
    const { editingPlugin, pluginsLoading } = useValues(pluginsLogic)
    const { editPlugin, saveEditedPlugin, uninstallPlugin } = useActions(pluginsLogic)
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
            footer={
                <>
                    <Popconfirm
                        placement="topLeft"
                        title="Are you sure you wish to uninstall this plugin?"
                        onConfirm={editingPlugin ? () => uninstallPlugin(editingPlugin.name) : () => {}}
                        okText="Yes"
                        cancelText="No"
                    >
                        <Button style={{ color: 'var(--red)', float: 'left' }} type="link">
                            <DeleteOutlined /> Uninstall
                        </Button>
                    </Popconfirm>
                    <Button onClick={() => editPlugin(null)}>Cancel</Button>
                    <Button type="primary" loading={pluginsLoading} onClick={() => form.submit()}>
                        Save
                    </Button>
                </>
            }
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
                            <Form.Item
                                key={configKey}
                                label={editingPlugin.configSchema[configKey].name || configKey}
                                name={configKey}
                            >
                                <Input />
                            </Form.Item>
                        ))}
                    </div>
                ) : null}
            </Form>
        </Modal>
    )
}
