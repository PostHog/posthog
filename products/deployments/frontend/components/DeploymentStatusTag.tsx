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

const STATUS_LABEL: Record<DeploymentStatus, string> = {
    ready: 'Ready',
    error: 'Error',
    building: 'Building',
    queued: 'Queued',
    initializing: 'Initializing',
    cancelled: 'Cancelled',
}

export function DeploymentStatusTag({ status }: { status: DeploymentStatus }): JSX.Element {
    return <LemonTag type={STATUS_TYPE[status]}>{STATUS_LABEL[status]}</LemonTag>
}
