import { IconFilter, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button, ButtonGroup, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { Link, LinkPrimitive } from 'lib/lemon-ui/Link'

export function DashboardSelectionFilterBar({
    type,
    summary,
    sourceTitle,
    sourceInsightUrl,
    targetCount,
    onClear,
}: {
    type: 'bi' | 'insight'
    summary: string
    sourceTitle: string
    sourceInsightUrl?: string
    targetCount: number
    onClear: () => void
}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const label = type === 'bi' ? 'BI' : 'Insight'
    const clearLabel = type === 'bi' ? 'Clear BI filters' : 'Clear insight filter'
    const target = type === 'bi' ? 'worksheet' : 'insight'
    const details = (
        <div className="ph-no-capture flex max-w-80 flex-col gap-2 text-xs">
            <span className="font-semibold break-words">{summary}</span>
            <span className="break-words">
                <span>Filter from </span>
                {todayRailNav ? (
                    <LinkPrimitive to={sourceInsightUrl} className="underline">
                        {sourceTitle}
                    </LinkPrimitive>
                ) : (
                    <Link to={sourceInsightUrl}>{sourceTitle}</Link>
                )}
            </span>
            {type === 'insight' && <span>The source insight stays unchanged.</span>}
            <span>{`${targetCount} ${target}${targetCount === 1 ? '' : 's'} filtered`}</span>
        </div>
    )
    return (
        <div
            className="ph-no-capture flex min-w-0 max-w-full"
            data-attr={type === 'bi' ? 'bi-dashboard-filter-bar' : 'dashboard-result-filter-bar'}
        >
            {todayRailNav ? (
                <Popover>
                    <ButtonGroup className="min-w-0 max-w-full">
                        <PopoverTrigger
                            render={
                                <Button
                                    variant="outline"
                                    className="min-w-0"
                                    aria-label={`${label} filter: ${summary}`}
                                />
                            }
                        >
                            <IconFilter />
                            <span className="max-w-64 truncate">{`${label}: ${summary}`}</span>
                        </PopoverTrigger>
                        <Button
                            variant="outline"
                            size="icon"
                            onClick={onClear}
                            aria-label={clearLabel}
                            tooltip={clearLabel}
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
                            aria-label={`${label} filter: ${summary}`}
                        >
                            <span className="max-w-64 truncate">{`${label}: ${summary}`}</span>
                        </LemonButton>
                    </LemonDropdown>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconX />}
                        className="rounded-l-none border-l-0"
                        onClick={onClear}
                        aria-label={clearLabel}
                        tooltip={clearLabel}
                    />
                </>
            )}
        </div>
    )
}
