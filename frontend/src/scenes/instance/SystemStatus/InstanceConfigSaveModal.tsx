import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
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
            <div className="text-secondary">
                Value will be changed
                {!isSecret && (
                    <>
                        {' from '}
                        <span className="font-bold text-text-3000">
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
                <span className="font-bold text-text-3000">
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

    const isChangingEnabledEmailSettings =
        instanceConfigEditingState.EMAIL_ENABLED !== false &&
        Object.keys(instanceConfigEditingState).find((key) => key.startsWith('EMAIL'))
    const isEnablingEmail = instanceConfigEditingState.EMAIL_ENABLED === true
    const changeNoun = Object.keys(instanceConfigEditingState).length === 1 ? 'change' : 'changes'

    return (
        <LemonModal
            title={`Confirm ${changeNoun} to instance configuration`}
            isOpen={isOpen}
            closable={!loading}
            onClose={onClose}
            width={576}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={onClose}
                        disabledReason={loading ? 'Saving in progress' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton type="secondary" status="danger" loading={loading} onClick={saveInstanceConfig}>
                        Apply {changeNoun}
                    </LemonButton>
                </>
            }
        >
            <div className="deprecated-space-y-2">
                {isChangingEnabledEmailSettings && (
                    <LemonBanner type="info">
                        As you are changing email settings and {isEnablingEmail ? 'enabling email' : 'email is enabled'}
                        , we'll attempt to send a test email so you can verify everything works.
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
                {loading && (
                    <div className="mt-4 text-success">
                        <b>{pluralize(updatedInstanceConfigCount || 0, 'change')} updated successfully.</b>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
