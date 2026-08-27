import { LemonTag } from '@posthog/lemon-ui'

import type { RequestPriorityEnumApi } from '../../generated/api.schemas'
import { featureRequestPriorityLabel } from './featureRequestOptions'

export function FeatureRequestPriorityBadge({ priority }: { priority: RequestPriorityEnumApi | null }): JSX.Element {
    const type =
        priority === 'high' ? 'danger' : priority === 'medium' ? 'warning' : priority === 'low' ? 'muted' : 'default'
    return (
        <LemonTag size="small" type={type}>
            {featureRequestPriorityLabel(priority)}
        </LemonTag>
    )
}
