import { LemonTag } from '@posthog/lemon-ui'
import { Badge } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export function DashboardSelectionFilterStatus({
    type,
    filtered,
    isSource,
}: {
    type: 'bi' | 'insight'
    filtered: boolean
    isSource: boolean
}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const active = filtered || isSource
    const filterStatus = filtered ? 'filtered' : isSource ? 'source' : 'unaffected'
    const status = filtered ? 'Filtered by selection' : isSource ? 'Filter source' : 'Not filtered'
    const attributes = { [`data-${type}-filter-status`]: filterStatus }
    return todayRailNav ? (
        <Badge
            className="shrink-0 whitespace-nowrap border-current"
            variant={active ? 'info' : 'default'}
            {...attributes}
        >
            {status}
        </Badge>
    ) : (
        <LemonTag className="shrink-0 whitespace-nowrap" type={active ? 'info' : 'default'} {...attributes}>
            {status}
        </LemonTag>
    )
}
