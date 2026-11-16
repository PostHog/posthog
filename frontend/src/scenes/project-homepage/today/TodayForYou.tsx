import { useActions, useValues } from 'kea'

import { IconArrowRight, IconChevronDown } from '@posthog/icons'
import { Button, Skeleton } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodayAiRow } from './TodayAiRow'
import { TodayForYouEmpty } from './TodayForYouEmpty'
import { type TodayForYouRow } from './todayForYouRows'
import { TodayGitHubRow } from './TodayGitHubRow'
import { TodayHighlightRow } from './TodayHighlightRow'
import { TodayHomeHeading } from './TodayHomeHeading'
import { todayLogic } from './todayLogic'
import { TodayNewProjectForYou } from './TodayNewProjectForYou'
import { reportWorkKind } from './todayNextStep'
import { TodayProductPushRow } from './TodayProductPushRow'
import { TodayReportRow } from './TodayReportRow'

function TodayRowsSkeleton(): JSX.Element {
    return (
        <ol className="TodayRows" aria-busy aria-label="Loading">
            {['w-3/5', 'w-4/5', 'w-1/2'].map((width) => (
                <li key={width} className="TodayRow">
                    <Skeleton className="TodayRow__iconSkeleton" />
                    <div className="flex flex-col gap-2 py-1">
                        <Skeleton className={`h-3.5 ${width}`} />
                        <Skeleton className="h-3 w-2/5" />
                    </div>
                </li>
            ))}
        </ol>
    )
}

function renderRow(row: TodayForYouRow): JSX.Element {
    switch (row.kind) {
        case 'report':
            return <TodayReportRow key={row.key} report={row.report} source={row.source} done={row.done} />
        case 'highlight':
            return <TodayHighlightRow key={row.key} item={row.item} position={row.position} done={row.done} />
        case 'product_push':
            return <TodayProductPushRow key={row.key} campaign={row.campaign} />
    }
}

function countFixes(rows: TodayForYouRow[]): number {
    return rows.filter((row) => row.kind === 'report' && !row.done && reportWorkKind(row.report) === 'implement').length
}

function TodayForYouBody(): JSX.Element | null {
    const { forYouReady, forYouRows, forYouVisibleRows, forYouFailedNote } = useValues(todayLogic)

    if (!forYouReady) {
        return <TodayRowsSkeleton />
    }
    if (forYouRows.rows.length === 0) {
        return forYouFailedNote ? null : <TodayForYouEmpty />
    }
    const fixCount = countFixes(forYouRows.rows)
    return (
        <>
            <TodayAiRow />
            {fixCount > 0 ? <TodayGitHubRow fixCount={fixCount} /> : null}
            <ol className="TodayRows">{forYouVisibleRows.map(renderRow)}</ol>
        </>
    )
}

function TodayForYouFooter(): JSX.Element | null {
    const { forYouReady, forYouCanShowMore, forYouCanShowLess, shownReportIds, moreReportsLoading, listExpanded } =
        useValues(todayLogic)
    const { showMoreForYou, setListExpanded } = useActions(todayLogic)

    if (!forYouReady || !(forYouCanShowMore || listExpanded.for_you || shownReportIds.length > 0)) {
        return null
    }
    return (
        <div className="TodayRows__footer">
            {forYouCanShowMore ? (
                <Button
                    className="TodayRows__more"
                    loading={moreReportsLoading}
                    onClick={() => showMoreForYou()}
                    data-attr="today-more-reports-show"
                >
                    <IconChevronDown className="TodayRows__moreIcon" aria-hidden />
                    <span>Show more</span>
                </Button>
            ) : forYouCanShowLess ? (
                <Button
                    className="TodayRows__more"
                    onClick={() => setListExpanded('for_you', false)}
                    data-attr="today-more-reports-hide"
                >
                    <IconChevronDown className="TodayRows__moreIcon rotate-180" aria-hidden />
                    <span>Show less</span>
                </Button>
            ) : (
                <span />
            )}
            {shownReportIds.length > 0 && (
                <LinkPrimitive to={urls.inbox()} className="TodayRows__inbox" data-attr="today-more-reports-inbox">
                    <span>Open the Inbox</span>
                    <IconArrowRight className="size-3.5" aria-hidden />
                </LinkPrimitive>
            )}
        </div>
    )
}

export function TodayForYou(): JSX.Element | null {
    const { forYouReady, forYouRows, forYouOpenCount, forYouFailedNote, isNewProject } = useValues(todayLogic)
    const { retryFailedLoads } = useActions(todayLogic)

    if (isNewProject && forYouReady && forYouRows.rows.length === 0 && !forYouFailedNote) {
        return <TodayNewProjectForYou />
    }

    return (
        <section className="TodayHome__list" aria-label="For you today">
            <div className="TodayHome__headingRow">
                <TodayHomeHeading count={forYouReady ? forYouOpenCount : undefined}>For you today</TodayHomeHeading>
            </div>
            <TodayForYouBody />
            {forYouFailedNote && (
                <div className="TodayHome__note flex flex-wrap items-center gap-x-2">
                    <span>{forYouFailedNote}</span>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => retryFailedLoads()}
                        data-attr="today-reports-retry"
                    >
                        Try again
                    </Button>
                </div>
            )}
            <TodayForYouFooter />
        </section>
    )
}
