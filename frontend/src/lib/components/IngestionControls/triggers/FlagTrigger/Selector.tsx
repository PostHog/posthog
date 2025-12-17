import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FlagSelector } from 'lib/components/FlagSelector'
import { IconCancel } from 'lib/lemon-ui/icons'

import { AccessControlLevel } from '~/types'

import { ingestionControlsLogic } from '../../ingestionControlsLogic'
import { flagTriggerLogic } from './flagTriggerLogic'

export const FlagTriggerSelector = (): JSX.Element => {
    const { resourceType } = useValues(ingestionControlsLogic)
    const { flag, loading } = useValues(flagTriggerLogic)
    const { onChange } = useActions(flagTriggerLogic)

    return (
        <div className="flex flex-row justify-start">
            <AccessControlAction resourceType={resourceType} minAccessLevel={AccessControlLevel.Editor}>
                {({ disabledReason }) => (
                    <FlagSelector
                        value={flag?.id ?? undefined}
                        onChange={(id, key) => {
                            onChange({ id, key, variant: null })
                        }}
                        disabledReason={(disabledReason ?? loading) ? 'Loading...' : undefined}
                        readOnly={!!disabledReason || loading}
                    />
                )}
            </AccessControlAction>
            {flag && (
                <AccessControlAction resourceType={resourceType} minAccessLevel={AccessControlLevel.Editor}>
                    <LemonButton
                        className="ml-2"
                        icon={<IconCancel />}
                        size="small"
                        type="secondary"
                        onClick={() => onChange(null)}
                        title="Clear selected flag"
                        loading={loading}
                    />
                </AccessControlAction>
            )}
        </div>
    )
}
