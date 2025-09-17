import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { pluralize } from 'lib/utils'
import { EnvironmentConfigOption, preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { InstanceSetting } from '~/types'

import { InstanceConfigSaveModal } from './InstanceConfigSaveModal'
import { MetricValue, RenderMetricValue } from './RenderMetricValue'
import { RenderMetricValueEdit } from './RenderMetricValueEdit'
import { ConfigMode, systemStatusLogic } from './systemStatusLogic'

export function InstanceConfigTab(): JSX.Element {
    const { configOptions, preflightLoading } = useValues(preflightLogic)
    const { editableInstanceSettings, instanceSettingsLoading, instanceConfigMode, instanceConfigEditingState } =
        useValues(systemStatusLogic)
    const { loadInstanceSettings, setInstanceConfigMode, updateInstanceConfigValue, clearInstanceConfigEditing } =
        useActions(systemStatusLogic)

    useOnMountEffect(loadInstanceSettings)

    useKeyboardHotkeys({
        e: {
            action: () => setInstanceConfigMode(ConfigMode.Edit),
            disabled: instanceConfigMode !== ConfigMode.View || instanceSettingsLoading,
        },
        escape: {
            action: () => discard(),
            disabled: instanceConfigMode !== ConfigMode.Edit || instanceSettingsLoading,
        },
        enter: {
            action: () => save(),
            disabled: instanceConfigMode !== ConfigMode.Edit || instanceSettingsLoading,
        },
    })

    const save = (): void => {
        if (Object.keys(instanceConfigEditingState).length) {
            setInstanceConfigMode(ConfigMode.Saving)
        } else {
            setInstanceConfigMode(ConfigMode.View)
        }
    }

    const discard = (): void => {
        setInstanceConfigMode(ConfigMode.View)
        clearInstanceConfigEditing()
    }

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
                const props: MetricValue = {
                    value: record.value,
                    key: record.key,
                    emptyNullLabel: 'Unset',
                    value_type: record.value_type,
                    isSecret: record.is_secret,
                }
                return instanceConfigMode === ConfigMode.View
                    ? RenderMetricValue(_, props)
                    : RenderMetricValueEdit({
                          ...props,
                          value: instanceConfigEditingState[record.key] ?? record.value,
                          onValueChanged: updateInstanceConfigValue,
                      })
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
            <div className="flex items-center gap-2 mb-4">
                <div className="flex-1">
                    <h3>Instance configuration</h3>
                    <div>
                        Changing these settings will take effect on your entire instance.{' '}
                        <Link
                            to="https://posthog.com/docs/self-host/configure/instance-settings"
                            target="_blank"
                            targetBlankIcon
                        >
                            Learn more
                        </Link>
                        .
                    </div>
                </div>
                {instanceConfigMode === ConfigMode.View ? (
                    <>
                        <LemonButton
                            type="primary"
                            onClick={() => setInstanceConfigMode(ConfigMode.Edit)}
                            data-attr="instance-config-edit-button"
                            disabled={instanceSettingsLoading}
                        >
                            Edit
                        </LemonButton>
                    </>
                ) : (
                    <>
                        {Object.keys(instanceConfigEditingState).length > 0 && (
                            <span className="text-warning-dark flex items-center gap-2">
                                <IconWarning className="text-xl" />
                                <span>
                                    You have <b>{Object.keys(instanceConfigEditingState).length}</b> unapplied{' '}
                                    {pluralize(
                                        Object.keys(instanceConfigEditingState).length,
                                        'change',
                                        undefined,
                                        false
                                    )}
                                </span>
                            </span>
                        )}
                        <LemonButton type="secondary" disabled={instanceSettingsLoading} onClick={discard}>
                            Discard changes
                        </LemonButton>
                        <LemonButton type="primary" disabled={instanceSettingsLoading} onClick={save}>
                            Save
                        </LemonButton>
                    </>
                )}
            </div>

            <LemonTable
                dataSource={editableInstanceSettings}
                columns={columns}
                loading={instanceSettingsLoading}
                rowKey="key"
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
            <InstanceConfigSaveModal
                isOpen={instanceConfigMode === ConfigMode.Saving}
                onClose={() => setInstanceConfigMode(ConfigMode.Edit)}
            />
        </>
    )
}
