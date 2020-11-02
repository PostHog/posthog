import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Button, Form, Input, Popconfirm, Switch } from 'antd'
import { DeleteOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import { PluginImage } from './PluginImage'
import { Link } from 'lib/components/Link'
import { Drawer } from 'lib/components/Drawer'

export function PluginDrawer(): JSX.Element {
    const { user } = useValues(userLogic)
    const { editingPlugin, loading } = useValues(pluginsLogic)
    const { editPlugin, savePluginConfig, uninstallPlugin } = useActions(pluginsLogic)
    const [form] = Form.useForm()

    const canDelete = user?.plugin_access.install && !editingPlugin?.from_json

    useEffect(() => {
        if (editingPlugin) {
            form.setFieldsValue({
                ...(editingPlugin.pluginConfig.config || {}),
                __enabled: editingPlugin.pluginConfig.enabled,
            })
        } else {
            form.resetFields()
        }
    }, [editingPlugin?.name])

    return (
        <Drawer
            forceRender={true}
            visible={!!editingPlugin}
            onClose={() => editPlugin(null)}
            width="min(90vw, 420px)"
            title={editingPlugin?.name}
            footer={
                <>
                    <div style={{ display: 'flex' }}>
                        <div style={{ flexGrow: 1 }}>
                            {canDelete && (
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
                            )}
                        </div>
                        <div>
                            <Button onClick={() => editPlugin(null)} style={{ marginRight: 16 }}>
                                Cancel
                            </Button>
                            <Button type="primary" loading={loading} onClick={() => form.submit()}>
                                Save
                            </Button>
                        </div>
                    </div>
                </>
            }
        >
            <Form form={form} layout="vertical" name="basic" onFinish={savePluginConfig}>
                {editingPlugin ? (
                    <div>
                        <div style={{ display: 'flex', marginBottom: 16 }}>
                            <div>
                                <PluginImage url={editingPlugin.url} />
                            </div>
                            <div style={{ flexGrow: 1, paddingLeft: 16 }}>
                                {editingPlugin.description}
                                <div>
                                    <Link to={editingPlugin.url} target="_blank" rel="noopener noreferrer">
                                        View plugin <ArrowRightOutlined />
                                    </Link>
                                </div>
                            </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                            <b style={{ paddingRight: 8 }}>Enabled</b>
                            <Form.Item
                                fieldKey="__enabled"
                                name="__enabled"
                                valuePropName="checked"
                                style={{ display: 'inline-block', marginBottom: 0 }}
                            >
                                <Switch />
                            </Form.Item>
                        </div>
                        <h3 className="l3" style={{ marginTop: 32 }}>
                            Configuration
                        </h3>
                        {Object.keys(editingPlugin.config_schema).map((configKey) => (
                            <Form.Item
                                key={configKey}
                                label={editingPlugin.config_schema[configKey].name || configKey}
                                name={configKey}
                                required={editingPlugin.config_schema[configKey].required}
                                rules={[
                                    {
                                        required: editingPlugin.config_schema[configKey].required,
                                        message: 'Please enter a value!',
                                    },
                                ]}
                            >
                                <Input />
                            </Form.Item>
                        ))}
                    </div>
                ) : null}
            </Form>
        </Drawer>
    )
}
