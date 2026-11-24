import { IconBug, IconCheckCircle, IconCircleDashed, IconClock, IconPause, IconXCircle } from '@posthog/icons'

import { IconErrorOutline } from 'lib/lemon-ui/icons'

import { PlatformAlertConfigurationStatus } from './platformAlertFormat'

interface StatusDisplay {
    label: string
    icon: JSX.Element
}

const STATUS_CONFIG: Partial<Record<PlatformAlertConfigurationStatus, StatusDisplay>> = {
    not_firing: { label: 'OK', icon: <IconCheckCircle className="text-success" /> },
    firing: { label: 'Firing', icon: <IconErrorOutline className="text-danger" /> },
    errored: { label: 'Errored', icon: <IconXCircle className="text-warning" /> },
    broken: { label: 'Broken', icon: <IconBug className="text-warning" /> },
    snoozed: { label: 'Snoozed', icon: <IconClock className="text-muted" /> },
    disabled: { label: 'Disabled', icon: <IconPause className="text-muted" /> },
    not_checked: { label: 'Not checked yet', icon: <IconCircleDashed className="text-muted" /> },
}

const UNKNOWN_STATUS_DISPLAY: Omit<StatusDisplay, 'label'> = { icon: <IconCircleDashed /> }

export function PlatformAlertStateLabel({
    status,
    count,
}: {
    status: PlatformAlertConfigurationStatus
    count?: number
}): JSX.Element {
    // A state added on the backend before this map knows it still renders.
    const { label, icon } = STATUS_CONFIG[status] ?? { ...UNKNOWN_STATUS_DISPLAY, label: status }
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
