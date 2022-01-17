import { useActions, useValues } from 'kea'
import { IconOpenInNew } from 'lib/components/icons'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import React, { useEffect } from 'react'
import { EnvironmentConfigOption, preflightLogic } from 'scenes/PreflightCheck/logic'
import { InstanceSetting } from '~/types'
import { RenderMetricValue } from './RenderMetricValue'
import { systemStatusLogic } from './systemStatusLogic'

export function InstanceConfigTab(): JSX.Element {
    const { configOptions, preflightLoading } = useValues(preflightLogic)
    const { editableInstanceSettings, instanceSettingsLoading } = useValues(systemStatusLogic)
    const { loadInstanceSettings } = useActions(systemStatusLogic)

    useEffect(() => {
        loadInstanceSettings()
    }, [])

    const columns: LemonTableColumns<InstanceSetting> = [
        {
            title: 'Key',
            dataIndex: 'key',
        },
        {
            title: 'Description',
            dataIndex: 'description',
        },
        {
            title: 'Value',
            render: function renderValue(_, record) {
                return RenderMetricValue({ value: record.value, key: record.key, metric: record.description })
            },
        },
    ]

    const envColumns: LemonTableColumns<EnvironmentConfigOption> = [
        {
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
            <h3 className="l3" style={{ marginTop: 32 }}>
                Instance configuration
            </h3>

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
