import { useActions, useValues } from 'kea'

import { IconChat, IconHome, IconPlus, IconTerminal } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'
import { TodayWorkItem, workItemTitle, workItemUrl } from '~/layout/today/todayWorkItems'

import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayNavItem } from './TodayNavItem'
import { reportIcon, reportMeta, reportSource, reportTitle } from './todaySignalReports'

function recentMeta(item: TodayWorkItem): string {
    const kind = item.kind === 'chat' ? 'Chat' : 'Session'
    return item.timestamp ? `${kind} · ${dayjs(item.timestamp).fromNow()}` : kind
}

export function TodayHomeSidebar(): JSX.Element {
    const { reportId, reports, topReports, reportsFailed, hoveredReportId, reportSummary, moreReportCount } =
        useValues(todayLogic)
    const { reportOpened, setHoveredReportId } = useActions(todayLogic)
    const { homeRecentItems, recentLoading } = useValues(todaySpacesLogic)

    return (
        <div className="TodaySidebar">
            <LemonButton type="primary" fullWidth center icon={<IconPlus />} to={urls.ai()} data-attr="today-new-chat">
                New chat
            </LemonButton>
            <div className="TodaySidebar__scroll">
                {(homeRecentItems.length > 0 || recentLoading) && (
                    <>
                        <div className="TodaySidebar__sectionLabel Today__label">Recent</div>
                        <div className="TodaySidebar__list">
                            {recentLoading && !homeRecentItems.length ? (
                                <>
                                    <LemonSkeleton className="h-12" />
                                    <LemonSkeleton className="h-12" />
                                </>
                            ) : (
                                homeRecentItems.map((item) => (
                                    <TodayNavItem
                                        key={`${item.kind}-${item.id}`}
                                        title={workItemTitle(item)}
                                        meta={recentMeta(item)}
                                        color="var(--color-text-secondary)"
                                        icon={item.kind === 'chat' ? <IconChat /> : <IconTerminal />}
                                        to={workItemUrl(item)}
                                        dataAttr={
                                            item.kind === 'chat' ? 'today-nav-recent-chat' : 'today-nav-recent-session'
                                        }
                                    />
                                ))
                            )}
                        </div>
                    </>
                )}
                <div className="TodaySidebar__sectionLabel Today__label">Today</div>
                <div className="TodaySidebar__list">
                    <TodayNavItem
                        title="Home"
                        meta={
                            topReports === null
                                ? reportsFailed
                                    ? 'Reports didn’t load'
                                    : 'Reading your project…'
                                : reportSummary
                        }
                        color="var(--color-text-secondary)"
                        icon={<IconHome />}
                        to={urls.projectHomepage()}
                        current={reportId === null}
                        dataAttr="today-nav-home"
                    />
                    {topReports === null && !reportsFailed ? (
                        <>
                            <LemonSkeleton className="h-12" />
                            <LemonSkeleton className="h-12" />
                        </>
                    ) : (
                        reports.map((report) => (
                            <TodayNavItem
                                key={report.id}
                                title={reportTitle(report)}
                                meta={reportMeta(report)}
                                color={reportSource(report).color}
                                icon={<TodayIcon icon={reportIcon(report)} />}
                                to={urls.todayReport(report.id)}
                                active={hoveredReportId === report.id}
                                current={reportId === report.id}
                                dataAttr="today-nav-report"
                                onClick={() => reportOpened(report, 'sidebar')}
                                onHoverChange={(hovered) => setHoveredReportId(hovered ? report.id : null)}
                            />
                        ))
                    )}
                </div>
                {moreReportCount > 0 && (
                    <Link to={urls.inbox()} className="TodaySidebar__more" data-attr="today-nav-inbox">
                        {`${moreReportCount} more in the Inbox`}
                    </Link>
                )}
            </div>
        </div>
    )
}
