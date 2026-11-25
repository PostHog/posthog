import { IconBug, IconCheckCircle, IconCircleDashed, IconClock, IconPause, IconXCircle } from '@posthog/icons'

import { IconErrorOutline } from 'lib/lemon-ui/icons'

import { PlatformAlertConfigurationApi } from './generated/api.schemas'
import { PlatformAlertConfigurationStatus, configurationStateCounts } from './platformAlertFormat'

const STATUS_CONFIG: Record<PlatformAlertConfigurationStatus, { label: string; icon: JSX.Element }> = {
    not_firing: { label: 'OK', icon: <IconCheckCircle className="text-success" /> },
    firing: { label: 'Firing', icon: <IconErrorOutline className="text-danger" /> },
    errored: { label: 'Errored', icon: <IconXCircle className="text-warning" /> },
    broken: { label: 'Broken', icon: <IconBug className="text-warning" /> },
    snoozed: { label: 'Snoozed', icon: <IconClock className="text-muted" /> },
    disabled: { label: 'Disabled', icon: <IconPause className="text-muted" /> },
    not_checked: { label: 'Not checked yet', icon: <IconCircleDashed className="text-muted" /> },
}

export function PlatformAlertStateSummary({
    configuration,
}: {
    configuration: PlatformAlertConfigurationApi
}): JSX.Element {
    const showCounts = configuration.enabled && configuration.alerts.length > 1
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {configurationStateCounts(configuration).map(({ status, count }) => {
                const { label, icon } = STATUS_CONFIG[status]
                return (
                    <span
                        key={status}
                        className="flex items-center gap-1 whitespace-nowrap"
                        data-attr={`platform-alert-state-summary-${status}`}
                    >
                        <span className="flex text-base">{icon}</span>
                        <span>{showCounts ? `${count} ${label}` : label}</span>
                    </span>
                )
            })}
        </div>
    )
}
