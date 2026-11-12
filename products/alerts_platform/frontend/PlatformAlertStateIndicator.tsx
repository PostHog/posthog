import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { BillingAlertConfigurationStateEnumApi as PlatformAlertStateApi } from './generated/api.schemas'

const STATE_CONFIG: Record<PlatformAlertStateApi, { label: string; type: LemonTagType }> = {
    [PlatformAlertStateApi.NotFiring]: { label: 'OK', type: 'success' },
    [PlatformAlertStateApi.Firing]: { label: 'Firing', type: 'danger' },
    [PlatformAlertStateApi.Errored]: { label: 'Errored', type: 'danger' },
    [PlatformAlertStateApi.Snoozed]: { label: 'Snoozed', type: 'muted' },
    [PlatformAlertStateApi.Broken]: { label: 'Broken', type: 'danger' },
}

const STATES_WITH_ERROR_TOOLTIP = new Set<PlatformAlertStateApi>([
    PlatformAlertStateApi.Errored,
    PlatformAlertStateApi.Broken,
])

export function PlatformAlertStateIndicator({
    state,
    enabled = true,
    firstEnabledAt = null,
    lastErrorMessage,
    snoozeUntil,
}: {
    state: PlatformAlertStateApi
    enabled?: boolean
    firstEnabledAt?: string | null
    lastErrorMessage?: string | null
    snoozeUntil?: string | null
}): JSX.Element {
    if (!enabled) {
        if (firstEnabledAt == null) {
            return (
                <LemonTag type="warning" data-attr="platform-alert-state-draft">
                    Draft
                </LemonTag>
            )
        }
        return (
            <LemonTag type="muted" data-attr="platform-alert-state-disabled">
                Disabled
            </LemonTag>
        )
    }
    const config = STATE_CONFIG[state] ?? { label: state, type: 'default' as LemonTagType }
    const tag = (
        <LemonTag type={config.type} data-attr={`platform-alert-state-${state}`}>
            {config.label}
        </LemonTag>
    )
    if (lastErrorMessage && STATES_WITH_ERROR_TOOLTIP.has(state)) {
        return <Tooltip title={lastErrorMessage}>{tag}</Tooltip>
    }
    if (state === PlatformAlertStateApi.Snoozed && snoozeUntil) {
        return (
            <Tooltip
                title={
                    <>
                        Until <TZLabel time={snoozeUntil} />
                    </>
                }
            >
                {tag}
            </Tooltip>
        )
    }
    return tag
}
