import { useActions, useValues } from 'kea'

import { IconFilter, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button, ButtonGroup, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { Link, LinkPrimitive } from 'lib/lemon-ui/Link'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'

export function BIDashboardFilterBar({ dashboardId }: { dashboardId: number }): JSX.Element | null {
    const { selection, targets, sourceInsightUrl } = useValues(biDashboardCrossFilterLogic({ dashboardId }))
    const { setSelection } = useActions(biDashboardCrossFilterLogic({ dashboardId }))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (!selection) {
        return null
    }
    const targetCount = Object.keys(targets).length
    const summary = selection.selection.labels.map(({ name, value }) => `${name}: ${value}`).join(', ')
    const clear = (): void => setSelection(null)
    const details = (
        <div className="ph-no-capture flex max-w-80 flex-col gap-2 text-xs">
            <span className="font-semibold break-words">{summary}</span>
            <span className="break-words">
                <span>Filter from </span>
                {todayRailNav ? (
                    <LinkPrimitive to={sourceInsightUrl} className="underline">
                        {selection.title}
                    </LinkPrimitive>
                ) : (
                    <Link to={sourceInsightUrl}>{selection.title}</Link>
                )}
            </span>
            <span>{`${targetCount} ${targetCount === 1 ? 'worksheet' : 'worksheets'} filtered`}</span>
        </div>
    )
    return (
        <div className="ph-no-capture flex min-w-0 max-w-full" data-attr="bi-dashboard-filter-bar">
            {todayRailNav ? (
                <Popover>
                    <ButtonGroup className="min-w-0 max-w-full">
                        <PopoverTrigger
                            render={
                                <Button variant="outline" className="min-w-0" aria-label={`BI filter: ${summary}`} />
                            }
                        >
                            <IconFilter />
                            <span className="max-w-64 truncate">{`BI: ${summary}`}</span>
                        </PopoverTrigger>
                        <Button
                            variant="outline"
                            size="icon"
                            onClick={clear}
                            aria-label="Clear BI filters"
                            tooltip="Clear BI filters"
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
                            aria-label={`BI filter: ${summary}`}
                        >
                            <span className="max-w-64 truncate">{`BI: ${summary}`}</span>
                        </LemonButton>
                    </LemonDropdown>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconX />}
                        className="rounded-l-none border-l-0"
                        onClick={clear}
                        aria-label="Clear BI filters"
                        tooltip="Clear BI filters"
                    />
                </>
            )}
        </div>
    )
}
