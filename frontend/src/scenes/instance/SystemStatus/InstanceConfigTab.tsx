import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDialog, Link } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { EnvironmentConfigOption, preflightLogic } from 'lib/logic/preflightLogic'

import { InstanceSetting } from '~/types'

import { InstanceSettingEditField } from './InstanceSettingEditField'
import { RenderMetricValue } from './RenderMetricValue'
import { systemStatusLogic } from './systemStatusLogic'

export function InstanceConfigTab(): JSX.Element {
    const { configOptions, preflightLoading, isCloudOrDev } = useValues(preflightLogic)
    const { databaseInstanceSettings, editableInstanceSettings, instanceSettingsLoading, instanceSettingUpdating } =
        useValues(systemStatusLogic)
    const { loadInstanceSettings, deleteStoredInstanceSetting } = useActions(systemStatusLogic)

    useOnMountEffect(loadInstanceSettings)

    const columns: LemonTableColumns<InstanceSetting> = [
        {
            title: 'Environment variable',
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
            title: 'Stored value',
            render: function renderValue(_, record) {
                return RenderMetricValue(_, {
                    value: record.value,
                    key: record.key,
                    emptyNullLabel: 'Unset',
                    value_type: record.value_type,
                    isSecret: record.is_secret,
                })
            },
        },
    ]

    const storedColumns: LemonTableColumns<InstanceSetting> = [
        ...columns,
        {
            title: '',
            width: 0,
            render: function renderDelete(_, record) {
                return (
                    <LemonButton
                        type="secondary"
                        status="danger"
                        size="small"
                        loading={instanceSettingUpdating === record.key}
                        disabledReason={instanceSettingUpdating ? 'Another setting is saving' : undefined}
                        data-attr="instance-setting-delete-stored-value"
                        onClick={() =>
                            LemonDialog.open({
                                title: `Delete the stored value of ${record.key}?`,
                                description: `PostHog will use the ${record.key} environment variable instead, or the default if it isn't set. This applies within about a minute.`,
                                primaryButton: {
                                    status: 'danger',
                                    children: 'Delete',
                                    onClick: () => deleteStoredInstanceSetting(record.key),
                                },
                            })
                        }
                    >
                        Delete
                    </LemonButton>
                )
            },
        },
    ]

    const editableColumns: LemonTableColumns<InstanceSetting> = [
        columns[0],
        columns[1],
        {
            title: 'Value',
            render: function renderValue(_, record) {
                return <InstanceSettingEditField key={String(record.value)} setting={record} />
            },
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
        <>
            <LemonBanner type="warning" className="mb-4">
                Instance settings are deprecated. Configure your instance with environment variables. Only the few
                settings used during incidents can still be changed here.
            </LemonBanner>

            {isCloudOrDev ? (
                <>
                    <div className="mb-4">
                        <h3>Live settings</h3>
                        <p>Changes apply to the whole instance within about a minute.</p>
                    </div>
                    <LemonTable
                        className="mb-4"
                        dataSource={editableInstanceSettings}
                        columns={editableColumns}
                        loading={instanceSettingsLoading}
                        rowKey="key"
                        data-attr="instance-settings-live-table"
                    />
                </>
            ) : null}

            <div className="mb-4">
                <h3>Settings stored in the database</h3>
                <p>
                    These values were saved from this page before it became read-only. A stored value overrides the
                    environment variable with the same name. To move a setting, set its environment variable, restart
                    PostHog, then delete the stored value here.
                </p>
            </div>

            <LemonTable
                dataSource={databaseInstanceSettings}
                columns={storedColumns}
                loading={instanceSettingsLoading}
                rowKey="key"
                emptyState="No settings are stored in the database. Environment variables configure this instance."
                data-attr="instance-settings-database-table"
            />

            <div className="my-4">
                <h3>Environment configuration</h3>
                <div>
                    These settings can only be modified by environment variables.{' '}
                    <Link to="https://posthog.com/docs/self-host/configure/environment-variables" target="_blank">
                        Learn more <IconOpenInNew style={{ verticalAlign: 'middle' }} />
                    </Link>
                    .
                </div>
            </div>
            <LemonTable dataSource={configOptions} columns={envColumns} loading={preflightLoading} rowKey="key" />
        </>
    )
}
