import { IconCode } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'
import { Form } from 'antd'
import { useActions, useValues } from 'kea'
import { Drawer } from 'lib/components/Drawer'
import { MOCK_NODE_PROCESS } from 'lib/constants'
import { IconLock } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { endWithPunctation } from 'lib/utils'
import React, { useEffect, useState } from 'react'
import {
    defaultConfigForPlugin,
    determineInvisibleFields,
    determineRequiredFields,
    getConfigSchemaArray,
    isValidField,
} from 'scenes/pipeline/configUtils'
import { PluginField } from 'scenes/plugins/edit/PluginField'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { userLogic } from 'scenes/userLogic'

import { canGloballyManagePlugins } from '../access'
import { PluginSource } from '../source/PluginSource'
import { PluginTags } from '../tabs/apps/components'
import { capabilitiesInfo } from './CapabilitiesInfo'
import { PluginJobOptions } from './interface-jobs/PluginJobOptions'

window.process = MOCK_NODE_PROCESS

function EnabledDisabledSwitch({
    value,
    onChange,
}: {
    value?: boolean
    onChange?: (value: boolean) => void
}): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <LemonSwitch checked={value || false} onChange={onChange} />
            <strong>{value ? 'Enabled' : 'Disabled'}</strong>
        </div>
    )
}

const SecretFieldIcon = (): JSX.Element => (
    <>
        <Tooltip
            placement="top-start"
            title="This is a secret write-only field. Its value is not available after saving."
        >
            <IconLock style={{ marginRight: 5 }} />
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

    const updateInvisibleAndRequiredFields = (): void => {
        setInvisibleFields(editingPlugin ? determineInvisibleFields(form.getFieldValue, editingPlugin) : [])
        setRequiredFields(editingPlugin ? determineRequiredFields(form.getFieldValue, editingPlugin) : [])
    }

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
                    <div className="flex space-x-2">
                        <LemonButton size="small" onClick={() => editPlugin(null)} data-attr="plugin-drawer-cancel">
                            Cancel
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="primary"
                            loading={loading}
                            onClick={form.submit}
                            data-attr="plugin-drawer-save"
                        >
                            Save
                        </LemonButton>
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
                                    <LemonButton
                                        icon={<IconCode />}
                                        onClick={() => setEditingSource(!editingSource)}
                                        data-attr="plugin-edit-source"
                                    >
                                        Edit source
                                    </LemonButton>
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
                                                    <LemonTag className="cursor-default">{capability}</LemonTag>
                                                </Tooltip>
                                            ))}
                                        {(editingPlugin.capabilities?.jobs || []).map((jobName) => (
                                            <Tooltip title="Custom job" key={jobName}>
                                                <LemonTag className="cursor-default">{jobName}</LemonTag>
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
