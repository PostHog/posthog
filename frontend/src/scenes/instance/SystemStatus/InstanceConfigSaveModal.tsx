import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { SystemStatusRow } from '~/types'

import { RenderMetricValue } from './RenderMetricValue'
import { systemStatusLogic } from './systemStatusLogic'

interface ChangeRowInterface extends Pick<SystemStatusRow, 'value'> {
    oldValue?: boolean | string | number | number[] | null
    metricKey: string
}

function ChangeRow({ metricKey, oldValue, value }: ChangeRowInterface): JSX.Element | null {
    if (value?.toString() === oldValue?.toString()) {
        return null
    }

    return (
        <div className="bg-border-light radius p-2">
            <div>
                <code>{metricKey}</code>
            </div>
            <div className="text-secondary">
                Value will be changed from{' '}
                <span className="font-bold text-text-3000">
                    {RenderMetricValue(null, { key: metricKey, value: oldValue, emptyNullLabel: 'Unset' })}
                </span>
                {' to '}
                <span className="font-bold text-text-3000">
                    {RenderMetricValue(null, { key: metricKey, value, emptyNullLabel: 'Unset' })}
                </span>
            </div>
        </div>
    )
}

export function InstanceConfigSaveModal({ onClose, isOpen }: { onClose: () => void; isOpen: boolean }): JSX.Element {
    const { instanceConfigEditingState, editableInstanceSettings, updatedInstanceConfigCount } =
        useValues(systemStatusLogic)
    const { saveInstanceConfig } = useActions(systemStatusLogic)
    const loading = updatedInstanceConfigCount !== null

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
                <div>The following {changeNoun} will be immediately applied to your instance.</div>
                {Object.keys(instanceConfigEditingState).map((key) => (
                    <ChangeRow
                        key={key}
                        metricKey={key}
                        value={instanceConfigEditingState[key]}
                        oldValue={editableInstanceSettings.find((record) => record.key === key)?.value}
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
