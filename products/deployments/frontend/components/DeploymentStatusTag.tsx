import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'

import { DeploymentStatus } from '../fixtures'

const STATUS_TYPE: Record<DeploymentStatus, LemonTagType> = {
    ready: 'success',
    error: 'danger',
    building: 'primary',
    queued: 'default',
    initializing: 'default',
    cancelled: 'muted',
}

const STATUS_LABEL: Record<Exclude<DeploymentStatus, 'ready'>, string> = {
    error: 'Error',
    building: 'Building',
    queued: 'Queued',
    initializing: 'Initializing',
    cancelled: 'Cancelled',
}

export function DeploymentStatusTag({
    status,
    isCurrent = false,
}: {
    status: DeploymentStatus
    isCurrent?: boolean
}): JSX.Element {
    const label = status === 'ready' ? (isCurrent ? 'Live' : 'Successful') : STATUS_LABEL[status]
    return <LemonTag type={STATUS_TYPE[status]}>{label}</LemonTag>
}
