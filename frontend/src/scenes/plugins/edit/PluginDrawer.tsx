import React, { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Button, Form, Space, Switch, Tag } from 'antd'
import { CodeOutlined, LockFilled } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { Drawer } from 'lib/components/Drawer'
import { defaultConfigForPlugin, doFieldRequirementsMatch, getConfigSchemaArray } from 'scenes/plugins/utils'
import { PluginSource } from '../source/PluginSource'
import { PluginConfigChoice, PluginConfigSchema } from '@posthog/plugin-scaffold'
import { PluginField } from 'scenes/plugins/edit/PluginField'
import { endWithPunctation } from 'lib/utils'
import { canGloballyManagePlugins } from '../access'
import { capabilitiesInfo } from './CapabilitiesInfo'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PluginJobOptions } from './interface-jobs/PluginJobOptions'
import { MOCK_NODE_PROCESS } from 'lib/constants'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { PluginTags } from '../tabs/apps/components'
import { Link } from '@posthog/lemon-ui'

window.process = MOCK_NODE_PROCESS

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
            <strong className="pl-2.5">{value ? 'Enabled' : 'Disabled'}</strong>
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
    const { editPlugin, savePluginConfig, setEditingSource, generateApiKeysIfNeeded, showPluginLogs } =
        useActions(pluginsLogic)

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
                    <div className="flex">
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
                    {/* TODO: Rework as Kea form with Lemon UI components */}
                    {editingPlugin ? (
                        <div>
                            <div className="flex gap-4">
                                <PluginImage plugin={editingPlugin} size="large" />
                                <div className="flex flex-col grow gap-2">
                                    <span>{endWithPunctation(editingPlugin.description)}</span>
                                    <div className="flex items-center">
                                        <PluginTags plugin={editingPlugin} />
                                        {editingPlugin.url && (
                                            <Link to={editingPlugin.url}>
                                                <i>⤷ Learn more</i>
                                            </Link>
                                        )}
                                    </div>
                                    <div className="flex items-center">
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

                            {editingPlugin.plugin_type === 'source' && canGloballyManagePlugins(user?.organization) ? (
                                <div>
                                    <Button
                                        type={editingSource ? 'default' : 'primary'}
                                        icon={<CodeOutlined />}
                                        onClick={() => setEditingSource(!editingSource)}
                                        data-attr="plugin-edit-source"
                                    >
                                        Edit source
                                    </Button>
                                </div>
                            ) : null}

                            {editingPlugin.capabilities && Object.keys(editingPlugin.capabilities).length > 0 ? (
                                <>
                                    <h3 className="l3 mt-8">Capabilities</h3>

                                    <div className="mt-1.5">
                                        {[
                                            ...(editingPlugin.capabilities.methods || []),
                                            ...(editingPlugin.capabilities.scheduled_tasks || []),
                                        ]
                                            .filter(
                                                (capability) => !['setupPlugin', 'teardownPlugin'].includes(capability)
                                            )
                                            .map((capability) => (
                                                <Tooltip title={capabilitiesInfo[capability] || ''} key={capability}>
                                                    <Tag className="Plugin__CapabilitiesTag">{capability}</Tag>
                                                </Tooltip>
                                            ))}
                                        {(editingPlugin.capabilities?.jobs || []).map((jobName) => (
                                            <Tooltip title="Custom job" key={jobName}>
                                                <Tag className="Plugin__CapabilitiesTag">{jobName}</Tag>
                                            </Tooltip>
                                        ))}
                                    </div>
                                </>
                            ) : null}

                            {!!(
                                editingPlugin.pluginConfig.id &&
                                editingPlugin.capabilities?.jobs?.length &&
                                editingPlugin.public_jobs &&
                                Object.keys(editingPlugin.public_jobs).length
                            ) && (
                                <PluginJobOptions
                                    pluginId={editingPlugin.id}
                                    pluginConfigId={editingPlugin.pluginConfig.id}
                                    capabilities={editingPlugin.capabilities}
                                    publicJobs={editingPlugin.public_jobs}
                                    onSubmit={() => showPluginLogs(editingPlugin.id)}
                                />
                            )}

                            <h3 className="l3 mt-8">Configuration</h3>
                            {getConfigSchemaArray(editingPlugin.config_schema).length === 0 ? (
                                <div>This app is not configurable.</div>
                            ) : null}
                            {getConfigSchemaArray(editingPlugin.config_schema).map((fieldConfig, index) => (
                                <React.Fragment key={fieldConfig.key || `__key__${index}`}>
                                    {fieldConfig.markdown && <LemonMarkdown>{fieldConfig.markdown}</LemonMarkdown>}
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
                                                        <LemonMarkdown className="mt-0.5">
                                                            {fieldConfig.hint}
                                                        </LemonMarkdown>
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
                                                <p className="text-danger">
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
            {editingPlugin?.plugin_type === 'source' && editingPlugin.id ? (
                <PluginSource
                    visible={editingSource}
                    close={() => setEditingSource(false)}
                    pluginId={editingPlugin.id}
                    pluginConfigId={editingPlugin.pluginConfig?.id}
                />
            ) : null}
        </>
    )
}
