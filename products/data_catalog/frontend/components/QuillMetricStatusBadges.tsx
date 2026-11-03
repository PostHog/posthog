import { Badge } from '@posthog/quill'

import { humanizeDefinitionKind } from '../common'
import type { DataCatalogMetricApi } from '../generated/api.schemas'

export function QuillMetricStatusBadges({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-1">
            <Badge variant={metric.status === 'approved' ? 'success' : 'warning'}>{metric.status}</Badge>
            {metric.is_drifted && <Badge variant="destructive">Drifted</Badge>}
            <Badge>{humanizeDefinitionKind(metric.definition_kind)}</Badge>
        </div>
    )
}
