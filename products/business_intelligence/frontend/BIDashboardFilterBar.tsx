import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { Badge, Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link, LinkPrimitive } from 'lib/lemon-ui/Link'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'

export function BIDashboardFilterBar({ dashboardId }: { dashboardId: number }): JSX.Element | null {
    const { selection, targets, sourceInsightUrl } = useValues(biDashboardCrossFilterLogic({ dashboardId }))
    const { setSelection } = useActions(biDashboardCrossFilterLogic({ dashboardId }))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (!selection) {
        return null
    }
    const clear = (): void => setSelection(null)
    return (
        <div
            className="flex min-w-0 max-w-full flex-wrap items-center gap-2 border-l border-primary pl-2"
            data-attr="bi-dashboard-filter-bar"
            data-quill={todayRailNav ? '' : undefined}
        >
            <div className="flex min-w-0 flex-wrap items-center gap-2" role="status">
                {todayRailNav ? <Badge>BI</Badge> : <LemonTag>BI</LemonTag>}
                {todayRailNav ? (
                    <LinkPrimitive
                        to={sourceInsightUrl}
                        className="max-w-48 truncate text-xs underline"
                        title={`Filter from ${selection.title}`}
                    >
                        {selection.title}
                    </LinkPrimitive>
                ) : (
                    <Link
                        to={sourceInsightUrl}
                        className="max-w-48 truncate text-xs"
                        title={`Filter from ${selection.title}`}
                    >
                        {selection.title}
                    </Link>
                )}
                {selection.selection.labels.map(({ name, value }, index) =>
                    todayRailNav ? (
                        <Badge key={index} className="min-w-0 max-w-full">
                            <span className="truncate">{`${name}: ${value}`}</span>
                        </Badge>
                    ) : (
                        <LemonTag key={index} className="max-w-full">
                            <span className="truncate">{`${name}: ${value}`}</span>
                        </LemonTag>
                    )
                )}
                <span className="text-secondary text-xs">{`${Object.keys(targets).length} worksheets filtered`}</span>
            </div>
            {todayRailNav ? (
                <Button onClick={clear}>Clear BI filters</Button>
            ) : (
                <LemonButton size="xsmall" onClick={clear}>
                    Clear BI filters
                </LemonButton>
            )}
        </div>
    )
}
