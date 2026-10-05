import { useActions } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { TodayReportCard } from '~/layout/today/todayPreviewCards'

import type { BriefingItemStateEnumApi } from 'products/today/frontend/generated/api.schemas'

import { todayLogic } from './todayLogic'
import { isSampleReportId } from './todaySampleReports'

const LABEL = 'Mark as resolved'

/** The X on a left-bar report row. It resolves the report, and the row stays in the list, crossed out. */
export function TodayReportResolveButton({
    card,
    state = 'open',
}: {
    card: TodayReportCard
    /** Read live: the card keeps the payload it was built with. */
    state?: BriefingItemStateEnumApi
}): JSX.Element | null {
    const { requestReportVerdict } = useActions(todayLogic)
    const { reportId } = card
    if (!reportId || state !== 'open' || isSampleReportId(reportId)) {
        return null
    }
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon-xs"
                        aria-label={LABEL}
                        className="text-muted-foreground"
                        onClick={() =>
                            requestReportVerdict(
                                {
                                    reportId,
                                    title: card.title,
                                    hasOpenPullRequest:
                                        card.pullRequestState === 'open' || card.pullRequestState === 'draft',
                                },
                                'resolve',
                                'sidebar_row'
                            )
                        }
                        data-attr="today-nav-item-resolve"
                    />
                }
            >
                <IconX />
            </TooltipTrigger>
            <TooltipContent>{LABEL}</TooltipContent>
        </Tooltip>
    )
}
