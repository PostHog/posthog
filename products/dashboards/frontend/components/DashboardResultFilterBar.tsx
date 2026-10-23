import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { Badge, Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link, LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { dashboardResultFilterLogic } from '../dashboardResultFilterLogic'

export function DashboardResultFilterBar({ dashboardId }: { dashboardId: number }): JSX.Element | null {
    const { selection, sourceInsight, targets } = useValues(dashboardResultFilterLogic({ dashboardId }))
    const { setSelection } = useActions(dashboardResultFilterLogic({ dashboardId }))
    const quill = useFeatureFlag('TODAY_RAIL_NAV')
    if (!selection) {
        return null
    }
    const href = sourceInsight ? urls.insightView(sourceInsight.short_id) : undefined
    return (
        <div
            className="flex min-w-0 max-w-full flex-wrap items-center gap-2 border-l border-primary pl-2"
            data-attr="dashboard-result-filter-bar"
            data-quill={quill ? '' : undefined}
        >
            {quill ? <Badge>Insight</Badge> : <LemonTag>Insight</LemonTag>}
            {quill ? (
                <LinkPrimitive to={href} className="max-w-48 truncate text-xs underline">
                    {sourceInsight?.name || 'Selected result'}
                </LinkPrimitive>
            ) : (
                <Link to={href} className="max-w-48 truncate text-xs">
                    {sourceInsight?.name || 'Selected result'}
                </Link>
            )}
            <span className="max-w-64 truncate text-xs" title={selection.label}>
                {selection.label}
            </span>
            <span className="text-xs text-secondary">{`${Object.keys(targets).length} insights filtered`}</span>
            {quill ? (
                <Button onClick={() => setSelection(null)}>Clear insight filter</Button>
            ) : (
                <LemonButton size="xsmall" onClick={() => setSelection(null)}>
                    Clear insight filter
                </LemonButton>
            )}
        </div>
    )
}
