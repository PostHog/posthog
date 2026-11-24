import { IconBug, IconCheckCircle, IconCircleDashed, IconClock, IconPause, IconXCircle } from '@posthog/icons'

import { IconErrorOutline } from 'lib/lemon-ui/icons'

import { PlatformAlertConfigurationStatus, STATUS_LABELS } from './platformAlertFormat'

const STATUS_ICONS: Record<PlatformAlertConfigurationStatus, JSX.Element> = {
    not_firing: <IconCheckCircle className="text-success" />,
    firing: <IconErrorOutline className="text-danger" />,
    errored: <IconXCircle className="text-warning" />,
    broken: <IconBug className="text-warning" />,
    snoozed: <IconClock className="text-muted" />,
    disabled: <IconPause className="text-muted" />,
    not_checked: <IconCircleDashed className="text-muted" />,
}

export function PlatformAlertStateLabel({
    status,
    count,
}: {
    status: PlatformAlertConfigurationStatus
    count?: number
}): JSX.Element {
    // A state added on the backend before these maps know it still renders.
    const label = STATUS_LABELS[status] ?? status
    const icon = STATUS_ICONS[status] ?? <IconCircleDashed />
    return (
        <span
            className="flex items-center gap-1 whitespace-nowrap"
            data-attr={`platform-alert-state-summary-${status}`}
        >
            <span className="flex text-base">{icon}</span>
            <span>{count === undefined ? label : `${count} ${label}`}</span>
        </span>
    )
}
