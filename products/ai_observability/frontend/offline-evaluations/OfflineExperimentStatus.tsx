import { LemonTag } from '@posthog/lemon-ui'

import type { OfflineExperimentReadApi } from '../generated/api.schemas'

const STATUS_PRESENTATION = {
    completed: { label: 'Completed', type: 'success' },
    uploading: { label: 'Uploading', type: 'warning' },
    failed: { label: 'Failed', type: 'danger' },
} as const

export function OfflineExperimentStatus({ status }: { status: OfflineExperimentReadApi['status'] }): JSX.Element {
    const { label, type } = STATUS_PRESENTATION[status]

    return <LemonTag type={type}>{label}</LemonTag>
}
