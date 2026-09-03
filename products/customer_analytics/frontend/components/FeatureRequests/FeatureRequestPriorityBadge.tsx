import { LemonTag } from '@posthog/lemon-ui'

import type { FeatureRequestPriorityEnumApi } from '../../generated/api.schemas'
import { featureRequestPriorityLabel } from './featureRequestOptions'

export function FeatureRequestPriorityBadge({
    priority,
}: {
    priority: FeatureRequestPriorityEnumApi | null
}): JSX.Element {
    const type =
        priority === 'high' ? 'danger' : priority === 'medium' ? 'warning' : priority === 'low' ? 'muted' : 'default'
    return (
        <LemonTag size="small" type={type}>
            {featureRequestPriorityLabel(priority)}
        </LemonTag>
    )
}
