import { LemonTag } from '@posthog/lemon-ui'

import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'
import { Breakdown } from '~/queries/schema/schema-general'

export function MetricBreakdownTag({
    breakdown,
    onRemove,
}: {
    breakdown: Breakdown
    onRemove: () => void
}): JSX.Element {
    const breakdownType = breakdown.type || 'event'

    return (
        <LemonTag type="muted" size="small" closable onClose={onRemove} data-attr="experiment-breakdown-tag">
            <PropertyKeyInfo
                value={extractDisplayLabel(String(breakdown.property))}
                type={PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[breakdownType]}
                disableIcon
            />
        </LemonTag>
    )
}
