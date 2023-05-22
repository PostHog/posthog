import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
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
    const { instanceConfigEditingState, editableInstanceSettings, isInstanceConfigSaveSubmitting } =
        useValues(systemStatusLogic)
    const { submitInstanceConfigSave } = useActions(systemStatusLogic)

    const changeNoun = Object.keys(instanceConfigEditingState).length === 1 ? 'change' : 'changes'

    return (
        <LemonModal
            title={`Confirm ${changeNoun} to instance configuration`}
            isOpen={isOpen}
            closable={!isInstanceConfigSaveSubmitting}
            onClose={onClose}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={onClose}
                        disabledReason={isInstanceConfigSaveSubmitting ? 'Saving in progress' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        loading={isInstanceConfigSaveSubmitting}
                        onClick={submitInstanceConfigSave}
                    >
                        Apply {changeNoun}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-2">
                {Object.keys(instanceConfigEditingState).find((key) => key.startsWith('EMAIL')) && (
                    <LemonBanner type="info">
                        <>
                            As you are changing email settings, we'll attempt to send a <b>test email</b> so you can
                            verify everything works (unless you are turning email off).
                        </>
                    </LemonBanner>
                )}
                {Object.keys(instanceConfigEditingState).includes('RECORDINGS_TTL_WEEKS') && (
                    <LemonBanner type="warning">
                        <>
                            Changing your recordings TTL requires ClickHouse to have enough free space to perform the
                            operation (even when reducing this value). In addition, please mind that removing old
                            recordings will be removed asynchronously, not immediately.
                        </>
                    </LemonBanner>
                )}
                {Object.keys(instanceConfigEditingState).includes('RECORDINGS_PERFORMANCE_EVENTS_TTL_WEEKS') && (
                    <LemonBanner type="warning">
                        <>
                            Changing your performance events TTL requires ClickHouse to have enough free space to
                            perform the operation (even when reducing this value). In addition, please mind that
                            removing old recordings will be removed asynchronously, not immediately.
                        </>
                    </LemonBanner>
                )}
                <div>The following {changeNoun} will be immediately applied to your instance.</div>
                {Object.keys(instanceConfigEditingState).map((key) => (
                    <ChangeRow
                        key={key}
                        metricKey={key}
                        value={instanceConfigEditingState[key]}
                        oldValue={editableInstanceSettings.find((record) => record.key === key)?.value}
                        isSecret={editableInstanceSettings.find((record) => record.key === key)?.is_secret}
                    />
                ))}
            </div>
        </LemonModal>
    )
}
