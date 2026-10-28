import { useActions, useValues } from 'kea'

import { IconFilter, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button, ButtonGroup, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { Link, LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { dashboardResultFilterLogic } from '../dashboardResultFilterLogic'

export function DashboardResultFilterBar({ dashboardId }: { dashboardId: number }): JSX.Element | null {
    const { selection, targets, sourceInsight } = useValues(dashboardResultFilterLogic({ dashboardId }))
    const { setSelection } = useActions(dashboardResultFilterLogic({ dashboardId }))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (!selection) {
        return null
    }
    const targetCount = Object.keys(targets).length
    const summary = selection.label
    const sourceInsightUrl = sourceInsight ? urls.insightView(sourceInsight.short_id) : undefined
    const clear = (): void => setSelection(null)
    const details = (
        <div className="ph-no-capture flex max-w-80 flex-col gap-2 text-xs">
            <span className="font-semibold break-words">{summary}</span>
            <span className="break-words">
                <span>Filter from </span>
                {todayRailNav ? (
                    <LinkPrimitive to={sourceInsightUrl} className="underline">
                        {sourceInsight?.name || 'Untitled insight'}
                    </LinkPrimitive>
                ) : (
                    <Link to={sourceInsightUrl}>{sourceInsight?.name || 'Untitled insight'}</Link>
                )}
            </span>
            <span>The source insight stays unchanged.</span>
            <span>{`${targetCount} ${targetCount === 1 ? 'insight' : 'insights'} filtered`}</span>
        </div>
    )
    return (
        <div className="ph-no-capture flex min-w-0 max-w-full" data-attr="dashboard-result-filter-bar">
            {todayRailNav ? (
                <Popover>
                    <ButtonGroup className="min-w-0 max-w-full">
                        <PopoverTrigger
                            render={
                                <Button
                                    variant="outline"
                                    className="min-w-0"
                                    aria-label={`Insight filter: ${summary}`}
                                />
                            }
                        >
                            <IconFilter />
                            <span className="max-w-64 truncate">{`Insight: ${summary}`}</span>
                        </PopoverTrigger>
                        <Button
                            variant="outline"
                            size="icon"
                            onClick={clear}
                            aria-label="Clear insight filter"
                            tooltip="Clear insight filter"
                        >
                            <IconX />
                        </Button>
                    </ButtonGroup>
                    <PopoverContent align="start">{details}</PopoverContent>
                </Popover>
            ) : (
                <>
                    <LemonDropdown overlay={details} placement="bottom-start">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconFilter />}
                            className="min-w-0 rounded-r-none"
                            aria-label={`Insight filter: ${summary}`}
                        >
                            <span className="max-w-64 truncate">{`Insight: ${summary}`}</span>
                        </LemonButton>
                    </LemonDropdown>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconX />}
                        className="rounded-l-none border-l-0"
                        onClick={clear}
                        aria-label="Clear insight filter"
                        tooltip="Clear insight filter"
                    />
                </>
            )}
        </div>
    )
}
