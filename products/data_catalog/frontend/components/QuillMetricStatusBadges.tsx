import { Badge } from '@posthog/quill'

import type { DataCatalogMetricApi } from '../generated/api.schemas'

const STATUS_LABELS: Record<string, string> = { approved: 'Approved', proposed: 'Proposed' }

export function QuillMetricStatusBadges({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-1">
            <Badge variant={metric.status === 'approved' ? 'success' : 'warning'}>
                {STATUS_LABELS[metric.status] ?? metric.status}
            </Badge>
            {metric.is_drifted && <Badge variant="destructive">Drifted</Badge>}
        </div>
    )
}
