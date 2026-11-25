import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { PlatformAlertConfigurationStatus, STATUS_LABELS } from './platformAlertFormat'

const STATUS_TAG_TYPES: Record<PlatformAlertConfigurationStatus, LemonTagType> = {
    not_firing: 'success',
    firing: 'danger',
    errored: 'danger',
    snoozed: 'muted',
    broken: 'danger',
    disabled: 'muted',
    not_checked: 'default',
}

export function PlatformAlertStatusTag({ status }: { status: PlatformAlertConfigurationStatus }): JSX.Element {
    // A state added on the backend before this map knows it still renders.
    return <LemonTag type={STATUS_TAG_TYPES[status] ?? 'default'}>{STATUS_LABELS[status] ?? status}</LemonTag>
}
