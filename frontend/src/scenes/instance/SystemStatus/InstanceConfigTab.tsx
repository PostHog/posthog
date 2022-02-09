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
import { systemStatusLogic } from './systemStatusLogic'

export enum ConfigMode {
    View = 'view',
    Edit = 'edit',
}

export function InstanceConfigTab(): JSX.Element {
    const { configOptions, preflightLoading } = useValues(preflightLogic)
    const { editableInstanceSettings, instanceSettingsLoading } = useValues(systemStatusLogic)
    const { loadInstanceSettings } = useActions(systemStatusLogic)
    const [mode, setMode] = useState(ConfigMode.View)
    const [editingValuesState, setEditingValuesState] = useState({} as Record<string, Pick<InstanceSetting, 'value'>>)

    useKeyboardHotkeys({
        e: {
            action: () => setMode(ConfigMode.Edit),
            disabled: mode !== ConfigMode.View,
        },
    })

    const handleValueChanged = (key: string, value: any): void => {
        setEditingValuesState({ ...editingValuesState, [key]: value })
    }

    const save = (): void => {
        console.log(editingValuesState)
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
                return mode === ConfigMode.Edit
                    ? RenderMetricValueEdit({
                          ...props,
                          value: editingValuesState[record.key] ?? record.value,
                          onValueChanged: handleValueChanged,
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
                {mode === ConfigMode.View ? (
                    <>
                        <HotkeyButton
                            type="primary"
                            onClick={() => setMode(ConfigMode.Edit)}
                            data-attr="instance-config-edit-button"
                            hotkey="e"
                            disabled={instanceSettingsLoading}
                        >
                            Edit
                        </HotkeyButton>
                    </>
                ) : (
                    <>
                        <Button
                            type="link"
                            style={{ color: 'var(--danger)' }}
                            disabled={instanceSettingsLoading}
                            onClick={() => setMode(ConfigMode.View)}
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
        </div>
    )
}
