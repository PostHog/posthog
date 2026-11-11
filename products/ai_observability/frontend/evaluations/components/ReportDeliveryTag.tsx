import { LemonTag } from '@posthog/lemon-ui'

import type { EvaluationReportRun } from '../types'

const DELIVERY_TAGS: Record<
    EvaluationReportRun['delivery_status'],
    { label: string; type: 'success' | 'warning' | 'danger' | 'muted' }
> = {
    delivered: { label: 'Delivered', type: 'success' },
    generated: { label: 'Generated', type: 'success' },
    pending: { label: 'Pending', type: 'muted' },
    partial_failure: { label: 'Partial failure', type: 'warning' },
    failed: { label: 'Failed', type: 'danger' },
}

export function ReportDeliveryTag({ status }: { status: EvaluationReportRun['delivery_status'] }): JSX.Element {
    const tag = DELIVERY_TAGS[status] ?? { label: status, type: 'muted' as const }
    return (
        <LemonTag type={tag.type} size="small">
            {tag.label}
        </LemonTag>
    )
}
