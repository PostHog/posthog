import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { PlatformAlertConfigurationStatus } from './platformAlertFormat'

const STATUS_CONFIG: Record<PlatformAlertConfigurationStatus, { label: string; type: LemonTagType }> = {
    not_firing: { label: 'OK', type: 'success' },
    firing: { label: 'Firing', type: 'danger' },
    errored: { label: 'Errored', type: 'danger' },
    snoozed: { label: 'Snoozed', type: 'muted' },
    broken: { label: 'Broken', type: 'danger' },
    disabled: { label: 'Disabled', type: 'muted' },
    not_checked: { label: 'Not checked yet', type: 'default' },
}

export function PlatformAlertStatusTag({ status }: { status: PlatformAlertConfigurationStatus }): JSX.Element {
    // A state added on the backend before this map knows it still renders.
    const { label, type } = STATUS_CONFIG[status] ?? { label: status, type: 'default' }
    return <LemonTag type={type}>{label}</LemonTag>
}
