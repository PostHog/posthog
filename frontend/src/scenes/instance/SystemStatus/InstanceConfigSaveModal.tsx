import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AlertMessage } from 'lib/components/AlertMessage'
import { pluralize } from 'lib/utils'
import { SystemStatusRow } from '~/types'
import { RenderMetricValue } from './RenderMetricValue'
import { systemStatusLogic } from './systemStatusLogic'

interface ChangeRowInterface extends Pick<SystemStatusRow, 'value'> {
    oldValue?: boolean | string | number | null
    metricKey: string
    isSecret?: boolean
}

function ChangeRow({ metricKey, oldValue, value, isSecret }: ChangeRowInterface): JSX.Element | null {
    if (value?.toString() === oldValue?.toString()) {
        return null
    }

    return (
        <div className="bg-border-light radius p-2">
            <div>
                <code>{metricKey}</code>
            </div>
            <div className="text-muted">
                Value will be changed
                {!isSecret && (
                    <>
                        {' from '}
                        <span className="font-bold text-default">
                            {RenderMetricValue(null, {
                                key: metricKey,
                                value: oldValue,
                                emptyNullLabel: 'Unset',
                                isSecret,
                            })}
                        </span>
                    </>
                )}
                {' to '}
                <span className="font-bold text-default">
                    {RenderMetricValue(null, { key: metricKey, value, emptyNullLabel: 'Unset' })}
                </span>
                {isSecret && (
                    <div className="text-danger">This field is secret - you won't see its value once saved</div>
                )}
            </div>
        </div>
    )
}

export function InstanceConfigSaveModal({ onClose, isOpen }: { onClose: () => void; isOpen: boolean }): JSX.Element {
    const { instanceConfigEditingState, editableInstanceSettings, updatedInstanceConfigCount } =
        useValues(systemStatusLogic)
    const { saveInstanceConfig } = useActions(systemStatusLogic)
    const loading = updatedInstanceConfigCount !== null
    return (
        <LemonModal
            title="Confirm new changes"
            isOpen={isOpen}
            closable={!loading}
            onClose={onClose}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose} loading={loading}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" status="danger" loading={loading} onClick={saveInstanceConfig}>
                        Apply changes
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-2">
                {Object.keys(instanceConfigEditingState).find((key) => key.startsWith('EMAIL')) && (
                    <AlertMessage type="info">
                        <>
                            As you are changing email settings, we'll attempt to send a <b>test email</b> so you can
                            verify everything works (unless you are turning email off).
                        </>
                    </AlertMessage>
                )}
                {Object.keys(instanceConfigEditingState).includes('RECORDINGS_TTL_WEEKS') && (
                    <AlertMessage type="warning">
                        <>
                            Changing your recordings TTL requires ClickHouse to have enough free space to perform the
                            operation (even when reducing this value). In addition, please mind that removing old
                            recordings will be removed asynchronously, not immediately.
                        </>
                    </AlertMessage>
                )}
                {Object.keys(instanceConfigEditingState).includes('RECORDINGS_PERFORMANCE_EVENTS_TTL_WEEKS') && (
                    <AlertMessage type="warning">
                        <>
                            Changing your performance events TTL requires ClickHouse to have enough free space to
                            perform the operation (even when reducing this value). In addition, please mind that
                            removing old recordings will be removed asynchronously, not immediately.
                        </>
                    </AlertMessage>
                )}
                <div>The following changes will be immediately applied to your instance.</div>
                {Object.keys(instanceConfigEditingState).map((key) => (
                    <ChangeRow
                        key={key}
                        metricKey={key}
                        value={instanceConfigEditingState[key]}
                        oldValue={editableInstanceSettings.find((record) => record.key === key)?.value}
                        isSecret={editableInstanceSettings.find((record) => record.key === key)?.is_secret}
                    />
                ))}
                {loading && (
                    <div className="mt-4 text-success">
                        <b>{pluralize(updatedInstanceConfigCount || 0, 'change')} updated successfully.</b>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
