import { useActions, useValues } from 'kea'

import { IconArrowRight, IconChevronDown } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { type TodayForYouRow } from './todayForYouRows'
import { TodayHighlightRow } from './TodayHighlightRow'
import { TodayHomeHeading } from './TodayHomeHeading'
import { todayLogic } from './todayLogic'
import { TodayReportRow } from './TodayReportRow'
import { TodayRowsSkeleton } from './TodayRowsSkeleton'

function renderRow(row: TodayForYouRow): JSX.Element {
    switch (row.kind) {
        case 'report':
            return <TodayReportRow key={row.key} report={row.report} source={row.source} done={row.done} />
        case 'highlight':
            return <TodayHighlightRow key={row.key} item={row.item} position={row.position} done={row.done} />
    }
}

export function TodayForYou(): JSX.Element {
    const {
        forYouReady,
        forYouRows,
        forYouVisibleRows,
        forYouOpenCount,
        forYouFailedNote,
        forYouCanShowMore,
        forYouCanShowLess,
        shownReportIds,
        moreReportsLoading,
        listExpanded,
        isNewProject,
    } = useValues(todayLogic)
    const { showMoreForYou, setListExpanded, retryFailedLoads } = useActions(todayLogic)

    return (
        <section className="TodayHome__list" aria-label="For you today">
            <div className="TodayHome__headingRow">
                <TodayHomeHeading count={forYouReady ? forYouOpenCount : undefined}>For you today</TodayHomeHeading>
            </div>
            {!forYouReady ? (
                <TodayRowsSkeleton />
            ) : forYouRows.rows.length === 0 ? (
                !forYouFailedNote && (
                    <p className="TodayHome__note">
                        {isNewProject
                            ? 'Once your project sends events, changes that need you show up here.'
                            : 'Nothing needs you today. Changes in your data that need you show up here.'}
                    </p>
                )
            ) : (
                <ol className="TodayRows">{forYouVisibleRows.map(renderRow)}</ol>
            )}
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
            {forYouReady && (forYouCanShowMore || listExpanded.for_you || shownReportIds.length > 0) && (
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
                        <LinkPrimitive
                            to={urls.inbox()}
                            className="TodayRows__inbox"
                            data-attr="today-more-reports-inbox"
                        >
                            <span>Open the Inbox</span>
                            <IconArrowRight className="size-3.5" aria-hidden />
                        </LinkPrimitive>
                    )}
                </div>
            )}
        </section>
    )
}
