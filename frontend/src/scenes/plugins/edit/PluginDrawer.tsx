import React, { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Button, Form, Popconfirm, Space, Switch, Tag } from 'antd'
import { DeleteOutlined, CodeOutlined, LockFilled, GlobalOutlined, RollbackOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { Drawer } from 'lib/components/Drawer'
import { LocalPluginTag } from 'scenes/plugins/plugin/LocalPluginTag'
import { defaultConfigForPlugin, doFieldRequirementsMatch, getConfigSchemaArray } from 'scenes/plugins/utils'
import Markdown from 'react-markdown'
import { SourcePluginTag } from 'scenes/plugins/plugin/SourcePluginTag'
import { PluginSource } from './PluginSource'
import { PluginConfigChoice, PluginConfigSchema } from '@posthog/plugin-scaffold'
import { PluginField } from 'scenes/plugins/edit/PluginField'
import { endWithPunctation } from 'lib/utils'
import { canGloballyManagePlugins, canInstallPlugins } from '../access'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { capabilitiesInfo } from './CapabilitiesInfo'
import { Tooltip } from 'lib/components/Tooltip'
import { PluginJobOptions } from './interface-jobs/PluginJobOptions'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

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
    const { preflight } = useValues(preflightLogic)
    const { editingPlugin, loading, editingSource, editingPluginInitialChanges } = useValues(pluginsLogic)
    const { editPlugin, savePluginConfig, uninstallPlugin, setEditingSource, generateApiKeysIfNeeded, patchPlugin } =
        useActions(pluginsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const [form] = Form.useForm()

    const [invisibleFields, setInvisibleFields] = useState<string[]>([])
    const [requiredFields, setRequiredFields] = useState<string[]>([])

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
        updateInvisibleAndRequiredFields()
    }, [editingPlugin?.id, editingPlugin?.config_schema])

    const updateInvisibleAndRequiredFields = (): void => {
        determineAndSetInvisibleFields()
        determineAndSetRequiredFields()
    }

    const determineAndSetInvisibleFields = (): void => {
        const fieldsToSetAsInvisible = []
        for (const field of Object.values(getConfigSchemaArray(editingPlugin?.config_schema || {}))) {
            if (!field.visible_if || !field.key) {
                continue
            }
            const shouldBeVisible = field.visible_if.every(
                ([targetFieldName, targetFieldValue]: Array<string | undefined>) =>
                    doFieldRequirementsMatch(form, targetFieldName, targetFieldValue)
            )

            if (!shouldBeVisible) {
                fieldsToSetAsInvisible.push(field.key)
            }
        }
        setInvisibleFields(fieldsToSetAsInvisible)
    }

    const determineAndSetRequiredFields = (): void => {
        const fieldsToSetAsRequired = []
        for (const field of Object.values(getConfigSchemaArray(editingPlugin?.config_schema || {}))) {
            if (!field.required_if || !Array.isArray(field.required_if) || !field.key) {
                continue
            }
            const shouldBeRequired = field.required_if.every(
                ([targetFieldName, targetFieldValue]: Array<string | undefined>) =>
                    doFieldRequirementsMatch(form, targetFieldName, targetFieldValue)
            )
            if (shouldBeRequired) {
                fieldsToSetAsRequired.push(field.key)
            }
        }

        setRequiredFields(fieldsToSetAsRequired)
    }

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
                width="min(90vw, 500px)"
                title={editingPlugin?.name}
                data-attr="plugin-drawer"
                footer={
                    <div style={{ display: 'flex' }}>
                        <Space style={{ flexGrow: 1 }}>
                            {editingPlugin &&
                                !editingPlugin.is_global &&
                                canInstallPlugins(user?.organization, editingPlugin.organization_id) && (
                                    <Popconfirm
                                        placement="topLeft"
                                        title="Are you sure you wish to uninstall this plugin completely?"
                                        onConfirm={() => uninstallPlugin(editingPlugin.name)}
                                        okText="Uninstall"
                                        cancelText="Cancel"
                                        className="plugins-popconfirm"
                                    >
                                        <Button
                                            style={{ color: 'var(--danger)', padding: 4 }}
                                            type="text"
                                            icon={<DeleteOutlined />}
                                            data-attr="plugin-uninstall"
                                        >
                                            Uninstall
                                        </Button>
                                    </Popconfirm>
                                )}
                            {preflight?.cloud &&
                                editingPlugin &&
                                canGloballyManagePlugins(user?.organization) &&
                                (editingPlugin.is_global ? (
                                    <Tooltip
                                        title={
                                            <>
                                                This plugin can currently be used by other organizations in this
                                                instance of PostHog. This action will <b>disable and hide it</b> for all
                                                organizations other than yours.
                                            </>
                                        }
                                    >
                                        <Button
                                            type="text"
                                            icon={<RollbackOutlined />}
                                            onClick={() => patchPlugin(editingPlugin.id, { is_global: false })}
                                            style={{ padding: 4 }}
                                        >
                                            Make local
                                        </Button>
                                    </Tooltip>
                                ) : (
                                    <Tooltip
                                        title={
                                            <>
                                                This action will mark this plugin as installed for{' '}
                                                <b>all organizations</b> in this instance of PostHog.
                                            </>
                                        }
                                    >
                                        <Button
                                            type="text"
                                            icon={<GlobalOutlined />}
                                            onClick={() => patchPlugin(editingPlugin.id, { is_global: true })}
                                            style={{ padding: 4 }}
                                        >
                                            Make global
                                        </Button>
                                    </Tooltip>
                                ))}
                        </Space>
                        <Space>
                            <Button onClick={() => editPlugin(null)} data-attr="plugin-drawer-cancel">
                                Cancel
                            </Button>
                            <Button
                                type="primary"
                                loading={loading}
                                onClick={form.submit}
                                data-attr="plugin-drawer-save"
                            >
                                Save
                            </Button>
                        </Space>
                    </div>
                }
            >
                <Form form={form} layout="vertical" name="basic" onFinish={savePluginConfig}>
                    {editingPlugin ? (
                        <div>
                            <div style={{ display: 'flex', marginBottom: 16 }}>
                                <PluginImage
                                    pluginType={editingPlugin.plugin_type}
                                    url={editingPlugin.url}
                                    size="large"
                                />
                                <div style={{ flexGrow: 1, paddingLeft: 16 }}>
                                    {endWithPunctation(editingPlugin.description)}
                                    <div style={{ marginTop: 5 }}>
                                        {editingPlugin?.plugin_type === 'local' && editingPlugin.url ? (
                                            <LocalPluginTag url={editingPlugin.url} title="Installed Locally" />
                                        ) : editingPlugin.plugin_type === 'source' ? (
                                            <SourcePluginTag />
                                        ) : null}
                                        {editingPlugin.url && (
                                            <a href={editingPlugin.url}>
                                                <i>⤷ Learn more</i>
                                            </a>
                                        )}
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', marginTop: 5 }}>
                                        <Form.Item
                                            fieldKey="__enabled"
                                            name="__enabled"
                                            style={{ display: 'inline-block', marginBottom: 0 }}
                                            data-attr="plugin-enabled-switch"
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
                                        data-attr="plugin-edit-source"
                                    >
                                        Edit Source
                                    </Button>
                                </div>
                            ) : null}

                            {editingPlugin.capabilities && Object.keys(editingPlugin.capabilities).length > 0 ? (
                                <>
                                    <h3 className="l3" style={{ marginTop: 32 }}>
                                        Capabilities
                                    </h3>

                                    <div style={{ marginTop: 5 }}>
                                        {[
                                            ...editingPlugin.capabilities.methods,
                                            ...editingPlugin.capabilities.scheduled_tasks,
                                        ]
                                            .filter(
                                                (capability) => !['setupPlugin', 'teardownPlugin'].includes(capability)
                                            )
                                            .map((capability) => (
                                                <Tooltip title={capabilitiesInfo[capability] || ''} key={capability}>
                                                    <Tag className="plugin-capabilities-tag">{capability}</Tag>
                                                </Tooltip>
                                            ))}
                                        {editingPlugin.capabilities.jobs.map((jobName) => (
                                            <Tooltip title="Custom job" key={jobName}>
                                                <Tag className="plugin-capabilities-tag">{jobName}</Tag>
                                            </Tooltip>
                                        ))}
                                    </div>
                                </>
                            ) : null}

                            {featureFlags[FEATURE_FLAGS.PLUGINS_UI_JOBS] && editingPlugin.pluginConfig.id ? (
                                <PluginJobOptions
                                    plugin={editingPlugin}
                                    pluginConfigId={editingPlugin.pluginConfig.id}
                                />
                            ) : null}

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
                                            hidden={!!fieldConfig.key && invisibleFields.includes(fieldConfig.key)}
                                            label={
                                                <>
                                                    {fieldConfig.secret && <SecretFieldIcon />}
                                                    {fieldConfig.name || fieldConfig.key}
                                                </>
                                            }
                                            extra={
                                                fieldConfig.hint && (
                                                    <small>
                                                        <div style={{ height: 2 }} />
                                                        <Markdown source={fieldConfig.hint} linkTarget="_blank" />
                                                    </small>
                                                )
                                            }
                                            name={fieldConfig.key}
                                            required={
                                                fieldConfig.required ||
                                                (!!fieldConfig.key && requiredFields.includes(fieldConfig.key))
                                            }
                                            rules={[
                                                {
                                                    required:
                                                        fieldConfig.required ||
                                                        (!!fieldConfig.key && requiredFields.includes(fieldConfig.key)),
                                                    message: 'Please enter a value!',
                                                },
                                            ]}
                                        >
                                            <PluginField
                                                fieldConfig={fieldConfig}
                                                onChange={updateInvisibleAndRequiredFields}
                                            />
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
