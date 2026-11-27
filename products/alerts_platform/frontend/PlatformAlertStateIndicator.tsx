import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { BillingAlertConfigurationStateEnumApi as PlatformAlertStateApi } from './generated/api.schemas'
import { STATUS_LABELS } from './platformAlertFormat'

const STATE_TAG_TYPES: Record<PlatformAlertStateApi, LemonTagType> = {
    [PlatformAlertStateApi.NotFiring]: 'success',
    [PlatformAlertStateApi.Firing]: 'danger',
    [PlatformAlertStateApi.Errored]: 'danger',
    [PlatformAlertStateApi.Snoozed]: 'muted',
    [PlatformAlertStateApi.Broken]: 'danger',
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
                {STATUS_LABELS.disabled}
            </LemonTag>
        )
    }
    const tag = (
        <LemonTag type={STATE_TAG_TYPES[state] ?? 'default'} data-attr={`platform-alert-state-${state}`}>
            {STATUS_LABELS[state] ?? state}
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
