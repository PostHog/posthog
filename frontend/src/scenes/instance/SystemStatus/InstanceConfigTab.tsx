import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { HotkeyButton } from 'lib/components/HotkeyButton/HotkeyButton'
import { IconOpenInNew } from 'lib/components/icons'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import React, { useEffect, useState } from 'react'
import { EnvironmentConfigOption, preflightLogic } from 'scenes/PreflightCheck/logic'
import { InstanceSetting } from '~/types'
import { RenderMetricValue } from './RenderMetricValue'
import { RenderMetricValueEdit } from './RenderMetricValueEdit'
import { ConfigMode, systemStatusLogic } from './systemStatusLogic'
import { WarningOutlined } from '@ant-design/icons'
import { InstanceConfigSaveModal } from './InstanceConfigSaveModal'

export function InstanceConfigTab(): JSX.Element {
    const { configOptions, preflightLoading } = useValues(preflightLogic)
    const { editableInstanceSettings, instanceSettingsLoading, instanceConfigMode, instanceConfigEditingState } =
        useValues(systemStatusLogic)
    const { loadInstanceSettings, setInstanceConfigMode, updateInstanceConfigValue, clearInstanceConfigEditing } =
        useActions(systemStatusLogic)
    const [saving, setSaving] = useState(false)

    useKeyboardHotkeys({
        e: {
            action: () => setInstanceConfigMode(ConfigMode.Edit),
            disabled: instanceConfigMode !== ConfigMode.View || instanceSettingsLoading,
        },
        escape: {
            action: () => setInstanceConfigMode(ConfigMode.View),
            disabled: instanceConfigMode !== ConfigMode.Edit || instanceSettingsLoading,
        },
        enter: {
            action: () => save(),
            disabled: instanceConfigMode !== ConfigMode.Edit || instanceSettingsLoading,
        },
    })

    const save = (): void => {
        if (Object.keys(instanceConfigEditingState).length) {
            setSaving(true)
        } else {
            setInstanceConfigMode(ConfigMode.View)
        }
    }

    useEffect(() => {
        loadInstanceSettings()
    }, [])

    const columns: LemonTableColumns<InstanceSetting> = [
        {
            title: 'Key',
            dataIndex: 'key',
            render: function render(value) {
                return <code>{value}</code>
            },
        },
        {
            title: 'Description',
            dataIndex: 'description',
        },
        {
            title: 'Value',
            render: function renderValue(_, record) {
                const props = {
                    value: record.value,
                    key: record.key,
                    emptyNullLabel: 'Unset',
                    value_type: record.value_type,
                }
                return instanceConfigMode === ConfigMode.Edit
                    ? RenderMetricValueEdit({
                          ...props,
                          value: instanceConfigEditingState[record.key] ?? record.value,
                          onValueChanged: updateInstanceConfigValue,
                      })
                    : RenderMetricValue(props)
            },
            width: 300,
        },
    ]

    const envColumns: LemonTableColumns<EnvironmentConfigOption> = [
        {
            key: 'metric',
            title: 'Metric',
            dataIndex: 'metric',
        },
        {
            title: 'Value',
            dataIndex: 'value',
        },
    ]

    return (
        <div>
            <div className="flex-center">
                <div style={{ flexGrow: 1 }}>
                    <h3 className="l3" style={{ marginTop: 16 }}>
                        Instance configuration
                    </h3>
                    <div className="mb text-muted">
                        Changing these settings will take effect on your entire instance.{' '}
                        <a href="https://posthog.com/docs/self-host/configure/instance-settings" target="_blank">
                            Learn more
                        </a>
                        .
                    </div>
                </div>
                {instanceConfigMode === ConfigMode.View ? (
                    <>
                        <HotkeyButton
                            type="primary"
                            onClick={() => setInstanceConfigMode(ConfigMode.Edit)}
                            data-attr="instance-config-edit-button"
                            hotkey="e"
                            disabled={instanceSettingsLoading}
                        >
                            Edit
                        </HotkeyButton>
                    </>
                ) : (
                    <>
                        {Object.keys(instanceConfigEditingState).length > 0 && (
                            <span style={{ color: 'var(--warning)' }}>
                                <WarningOutlined /> You have <b>{Object.keys(instanceConfigEditingState).length}</b>{' '}
                                unapplied changes
                            </span>
                        )}
                        <Button
                            type="link"
                            disabled={instanceSettingsLoading}
                            onClick={() => {
                                setInstanceConfigMode(ConfigMode.View)
                                clearInstanceConfigEditing()
                            }}
                        >
                            Discard changes
                        </Button>
                        <Button type="primary" disabled={instanceSettingsLoading} onClick={save}>
                            Save
                        </Button>
                    </>
                )}
            </div>

            <LemonTable
                dataSource={editableInstanceSettings}
                columns={columns}
                loading={instanceSettingsLoading}
                rowKey="key"
            />

            <h3 className="l3" style={{ marginTop: 32 }}>
                Environment configuration
            </h3>
            <p>
                These settings can only be modified by environment variables.{' '}
                <a href="https://posthog.com/docs/self-host/configure/environment-variables" target="_blank">
                    Learn more <IconOpenInNew style={{ verticalAlign: 'middle' }} />
                </a>
            </p>
            <LemonTable dataSource={configOptions} columns={envColumns} loading={preflightLoading} rowKey="key" />
            {saving && <InstanceConfigSaveModal onClose={() => setSaving(false)} />}
        </div>
    )
}
