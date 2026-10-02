import { useActions, useValues } from 'kea'

import { Button, Spinner } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { todayLogic } from './todayLogic'
import { TodayReportNavItem } from './TodayReportNavItem'

/** The reports for the person past the ones the sidebar lists, loaded on request. */
export function TodayMoreReports(): JSX.Element | null {
    const {
        canLoadMoreReports,
        moreReports,
        moreReportsLoading,
        sidebarMoreReports,
        moreReportPreviews,
        moreReportsInInbox,
    } = useValues(todayLogic)
    const { loadMoreReports } = useActions(todayLogic)

    if (canLoadMoreReports) {
        return (
            <Button
                variant="link-muted"
                size="sm"
                className="TodaySidebar__more"
                // The spinner sits next to the label rather than over it: quill's `loading` overlays the
                // button's box, which on this left-aligned link lands above the text.
                disabled={moreReportsLoading}
                onClick={loadMoreReports}
                data-attr="today-nav-load-more"
            >
                {moreReportsLoading && <Spinner />}
                Show more reports
            </Button>
        )
    }
    if (!moreReports) {
        return null
    }
    return (
        <>
            {sidebarMoreReports.map((report) => (
                <TodayReportNavItem
                    key={report.id}
                    report={report}
                    preview={moreReportPreviews.sidebar[report.id]}
                    source="sidebar_more"
                    dataAttr="today-nav-more-report"
                />
            ))}
            {moreReportsInInbox > 0 ? (
                <Button
                    variant="link-muted"
                    size="sm"
                    className="TodaySidebar__more"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.inbox()} />}
                    data-attr="today-nav-more-inbox"
                >
                    {moreReportsInInbox} more for you in the Inbox
                </Button>
            ) : sidebarMoreReports.length === 0 ? (
                <p className="TodaySidebar__more TodaySidebar__more--empty">No other reports need you right now</p>
            ) : null}
        </>
    )
}
