import { Modal } from 'antd'
import { useValues } from 'kea'
import { AlertMessage } from 'lib/components/InfoMessage/AlertMessage'
import React from 'react'
import { RenderMetricValue } from './RenderMetricValue'
import { MetricRow, systemStatusLogic } from './systemStatusLogic'

interface ChangeRowInterface extends Pick<MetricRow, 'value'> {
    old_value: any
    metricKey: string
}

function ChangeRow({ metricKey, old_value, value }: ChangeRowInterface): JSX.Element {
    return (
        <div
            style={{ backgroundColor: 'var(--border-light)', borderRadius: 'var(--radius)', padding: 8, marginTop: 16 }}
        >
            <div>
                <code>{metricKey}</code>
            </div>
            <div style={{ color: 'var(--text-muted)' }}>
                Value will be changed from{' '}
                <span style={{ color: 'var(--text-default)', fontWeight: 'bold' }}>
                    {RenderMetricValue({ key: metricKey, value: old_value })}
                </span>{' '}
                to{' '}
                <span style={{ color: 'var(--text-default)', fontWeight: 'bold' }}>
                    {RenderMetricValue({ key: metricKey, value })}
                </span>
            </div>
        </div>
    )
}

export function InstanceConfigSaveModal({ onClose }: { onClose: () => void }): JSX.Element {
    const { instanceConfigEditingState, editableInstanceSettings } = useValues(systemStatusLogic)
    return (
        <Modal
            title="Confirm new changes"
            visible
            okText="Apply changes"
            okType="danger"
            onCancel={onClose}
            maskClosable={false}
        >
            {Object.keys(instanceConfigEditingState).find((key) => key.startsWith('EMAIL')) && (
                <AlertMessage style={{ marginBottom: 16 }}>
                    <>
                        As you are changing email settings, we'll attempt to send a <b>test email</b> so you can verify
                        everything works (unless you are turning email off).
                    </>
                </AlertMessage>
            )}
            {Object.keys(instanceConfigEditingState).includes('RECORDINGS_TTL_WEEKS') && (
                <AlertMessage style={{ marginBottom: 16 }} type="warning">
                    <>
                        Changing your recordings TTL requires Clickhouse to have enough free space to perform the
                        operation (even when reducing this value). In addition, please mind that removing old recordings
                        will happen asynchronously.
                    </>
                </AlertMessage>
            )}
            <div>The following changes will be immediately applied to your instance.</div>
            {Object.keys(instanceConfigEditingState).map((key) => (
                <ChangeRow
                    key={key}
                    metricKey={key}
                    value={instanceConfigEditingState[key]}
                    old_value={editableInstanceSettings.find((record) => record.key === key)?.value}
                />
            ))}
        </Modal>
    )
}
