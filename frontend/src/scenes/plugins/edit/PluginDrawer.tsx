import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Button, Checkbox, Form, Popconfirm, Switch, Tooltip } from 'antd'
import { DeleteOutlined, CodeOutlined, LockFilled } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { Link } from 'lib/components/Link'
import { Drawer } from 'lib/components/Drawer'
import { LocalPluginTag } from 'scenes/plugins/plugin/LocalPluginTag'
import { defaultConfigForPlugin, getConfigSchemaArray } from 'scenes/plugins/utils'
import Markdown from 'react-markdown'
import { SourcePluginTag } from 'scenes/plugins/plugin/SourcePluginTag'
import { PluginSource } from './PluginSource'
import { PluginConfigChoice, PluginConfigSchema } from '@posthog/plugin-scaffold'
import { PluginsAccessLevel } from 'lib/constants'
import { PluginField } from 'scenes/plugins/edit/PluginField'
import { endWithPunctation } from '../../../lib/utils'

function EnabledDisabledSwitch({
    value,
    onChange,
}: {
    value?: boolean
    onChange?: (value: boolean) => void
}): JSX.Element {
    return (
        <>
            <Switch checked={value} onChange={onChange} />
            <strong style={{ paddingLeft: 10 }}>{value ? 'Enabled' : 'Disabled'}</strong>
        </>
    )
}

const SecretFieldIcon = (): JSX.Element => (
    <>
        <Tooltip
            placement="topLeft"
            title="This is a secret write-only field. Its value is not available after saving."
        >
            <LockFilled style={{ marginRight: 5 }} />
        </Tooltip>
    </>
)

export function PluginDrawer(): JSX.Element {
    const { user } = useValues(userLogic)
    const { editingPlugin, loading, editingSource, editingPluginInitialChanges } = useValues(pluginsLogic)
    const {
        editPlugin,
        savePluginConfig,
        uninstallPlugin,
        setEditingSource,
        generateApiKeysIfNeeded,
        patchPlugin,
    } = useActions(pluginsLogic)
    const [form] = Form.useForm()

    useEffect(() => {
        if (editingPlugin) {
            form.setFieldsValue({
                ...(editingPlugin.pluginConfig.config || defaultConfigForPlugin(editingPlugin)),
                __enabled: editingPlugin.pluginConfig.enabled,
                ...editingPluginInitialChanges,
            })
            generateApiKeysIfNeeded(form)
        } else {
            form.resetFields()
        }
    }, [editingPlugin?.id])

    const isValidChoiceConfig = (fieldConfig: PluginConfigChoice): boolean => {
        return (
            Array.isArray(fieldConfig.choices) &&
            !!fieldConfig.choices.length &&
            !fieldConfig.choices.find((c) => typeof c !== 'string') &&
            !fieldConfig.secret
        )
    }

    const isValidField = (fieldConfig: PluginConfigSchema): boolean =>
        fieldConfig.type !== 'choice' || isValidChoiceConfig(fieldConfig)

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
                                {editingPlugin?.organization_id === user?.organization?.id &&
                                    (user?.organization?.plugins_access_level ?? 0) >= PluginsAccessLevel.Install && (
                                        <Popconfirm
                                            placement="topLeft"
                                            title="Are you sure you wish to uninstall this plugin?"
                                            onConfirm={
                                                editingPlugin ? () => uninstallPlugin(editingPlugin.name) : () => {}
                                            }
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
                                <PluginImage pluginType={editingPlugin.plugin_type} url={editingPlugin.url} />
                                <div style={{ flexGrow: 1, paddingLeft: 16 }}>
                                    {endWithPunctation(editingPlugin.description)}
                                    {editingPlugin.url ? (
                                        <>
                                            {editingPlugin.description ? ' ' : ''}
                                            <Link
                                                to={editingPlugin.url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                style={{ whiteSpace: 'nowrap' }}
                                            >
                                                Learn more.
                                            </Link>
                                        </>
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

                            {user?.organization?.plugins_access_level === PluginsAccessLevel.Root &&
                                user?.is_multi_tenancy && (
                                    <>
                                        <h3 className="l3" style={{ marginTop: 32 }}>
                                            Installation
                                        </h3>
                                        <Tooltip
                                            title={
                                                <>
                                                    Enabling this will mark this plugin as installed for{' '}
                                                    <b>all organizations</b> in this instance of PostHog.
                                                </>
                                            }
                                            placement="bottom"
                                        >
                                            <Checkbox
                                                checked={editingPlugin.is_global}
                                                onChange={(e) =>
                                                    patchPlugin(editingPlugin.id, {
                                                        is_global: e.target.checked,
                                                    })
                                                }
                                            >
                                                <span style={{ paddingLeft: 10 }}>Mark as global</span>
                                            </Checkbox>
                                        </Tooltip>
                                    </>
                                )}

                            <h3 className="l3" style={{ marginTop: 32 }}>
                                Configuration
                            </h3>
                            {getConfigSchemaArray(editingPlugin.config_schema).length === 0 ? (
                                <div>This plugin is not configurable.</div>
                            ) : null}
                            {getConfigSchemaArray(editingPlugin.config_schema).map((fieldConfig, index) => (
                                <React.Fragment key={fieldConfig.key || `__key__${index}`}>
                                    {fieldConfig.markdown && (
                                        <Markdown source={fieldConfig.markdown} linkTarget="_blank" />
                                    )}
                                    {fieldConfig.type && isValidField(fieldConfig) ? (
                                        <Form.Item
                                            label={
                                                <>
                                                    {fieldConfig.secret && <SecretFieldIcon />}
                                                    {fieldConfig.name || fieldConfig.key}
                                                </>
                                            }
                                            extra={
                                                fieldConfig.hint && (
                                                    <Markdown source={fieldConfig.hint} linkTarget="_blank" />
                                                )
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
                                            <PluginField fieldConfig={fieldConfig} />
                                        </Form.Item>
                                    ) : (
                                        <>
                                            {fieldConfig.type ? (
                                                <p style={{ color: 'var(--danger)' }}>
                                                    Invalid config field <i>{fieldConfig.name || fieldConfig.key}</i>.
                                                </p>
                                            ) : null}
                                        </>
                                    )}
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
