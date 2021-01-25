import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Button, Form, Input, Popconfirm, Switch } from 'antd'
import { DeleteOutlined, CodeOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { Link } from 'lib/components/Link'
import { Drawer } from 'lib/components/Drawer'
import { LocalPluginTag } from 'scenes/plugins/plugin/LocalPluginTag'
import { UploadField } from './UploadField'
import { getConfigSchemaArray } from 'scenes/plugins/utils'
import Markdown from 'react-markdown'
import { SourcePluginTag } from 'scenes/plugins/plugin/SourcePluginTag'
import { PluginSource } from './PluginSource'

function EnabledDisabledSwitch({
    value,
    onChange,
}: {
    value?: boolean
    onChange?: (value: boolean) => void
}): JSX.Element {
    return (
        <>
            <Switch checked={value} onChange={onChange} />{' '}
            <strong style={{ paddingLeft: 8 }}>{value ? 'Enabled' : 'Disabled'}</strong>
        </>
    )
}

export function PluginDrawer(): JSX.Element {
    const { user } = useValues(userLogic)
    const { editingPlugin, loading, editingSource, editingPluginInitialChanges } = useValues(pluginsLogic)
    const { editPlugin, savePluginConfig, uninstallPlugin, setEditingSource, generateApiKeysIfNeeded } = useActions(
        pluginsLogic
    )
    const [form] = Form.useForm()

    const canDelete = user?.plugin_access.install

    useEffect(() => {
        if (editingPlugin) {
            form.setFieldsValue({
                ...(editingPlugin.pluginConfig.config || {}),
                __enabled: editingPlugin.pluginConfig.enabled,
                ...editingPluginInitialChanges,
            })
            generateApiKeysIfNeeded(form)
        } else {
            form.resetFields()
        }
    }, [editingPlugin?.id])

    return (
        <>
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
                                        okText="Uninstall"
                                        cancelText="Cancel"
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
                                <Button type="primary" loading={loading} onClick={form.submit}>
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
                                    <PluginImage pluginType={editingPlugin.plugin_type} url={editingPlugin.url} />
                                </div>
                                <div style={{ flexGrow: 1, paddingLeft: 16 }}>
                                    {editingPlugin.description}
                                    {editingPlugin.description?.substr(-1) !== '.' ? '.' : ''}
                                    {editingPlugin.url ? (
                                        <span>
                                            {editingPlugin.description ? ' ' : ''}
                                            <Link
                                                to={editingPlugin.url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                style={{ whiteSpace: 'nowrap' }}
                                            >
                                                Learn More
                                            </Link>
                                            .
                                        </span>
                                    ) : null}
                                    <div style={{ marginTop: 5 }}>
                                        {editingPlugin?.plugin_type === 'local' && editingPlugin.url ? (
                                            <LocalPluginTag url={editingPlugin.url} title="Installed Locally" />
                                        ) : editingPlugin.plugin_type === 'source' ? (
                                            <SourcePluginTag />
                                        ) : null}
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', marginTop: 5 }}>
                                        <Form.Item
                                            fieldKey="__enabled"
                                            name="__enabled"
                                            style={{ display: 'inline-block', marginBottom: 0 }}
                                        >
                                            <EnabledDisabledSwitch />
                                        </Form.Item>
                                    </div>
                                </div>
                            </div>

                            {editingPlugin.plugin_type === 'source' ? (
                                <div>
                                    <Button
                                        type={editingSource ? 'default' : 'primary'}
                                        icon={<CodeOutlined />}
                                        onClick={() => setEditingSource(!editingSource)}
                                    >
                                        Edit Source
                                    </Button>
                                </div>
                            ) : null}

                            <h3 className="l3" style={{ marginTop: 32 }}>
                                Configuration
                            </h3>
                            {getConfigSchemaArray(editingPlugin.config_schema).length === 0 ? (
                                <div>This plugin is not configurable.</div>
                            ) : null}
                            {getConfigSchemaArray(editingPlugin.config_schema).map((fieldConfig, index) => (
                                <React.Fragment key={fieldConfig.key || `__key__${index}`}>
                                    {fieldConfig.markdown ? (
                                        <Markdown source={fieldConfig.markdown} linkTarget="_blank" />
                                    ) : null}
                                    {fieldConfig.type ? (
                                        <Form.Item
                                            label={fieldConfig.name || fieldConfig.key}
                                            extra={
                                                fieldConfig.hint ? (
                                                    <Markdown source={fieldConfig.hint} linkTarget="_blank" />
                                                ) : null
                                            }
                                            name={fieldConfig.key}
                                            required={fieldConfig.required}
                                            rules={[
                                                {
                                                    required: fieldConfig.required,
                                                    message: 'Please enter a value!',
                                                },
                                            ]}
                                        >
                                            {fieldConfig.type === 'attachment' ? (
                                                <UploadField />
                                            ) : fieldConfig.type === 'string' ? (
                                                <Input />
                                            ) : (
                                                <strong style={{ color: 'var(--red)' }}>
                                                    Unknown field type "<code>{fieldConfig.type}</code>".
                                                    <br />
                                                    You may need to upgrade PostHog!
                                                </strong>
                                            )}
                                        </Form.Item>
                                    ) : null}
                                </React.Fragment>
                            ))}
                        </div>
                    ) : null}
                </Form>
            </Drawer>
            {editingPlugin?.plugin_type === 'source' ? <PluginSource /> : null}
        </>
    )
}
