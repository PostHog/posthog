import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconHome, IconPlus } from '@posthog/icons'
import { Button, Skeleton } from '@posthog/quill'

import { Link, LinkPrimitive } from 'lib/lemon-ui/Link'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { itemHref, itemSource } from './todayBriefingItems'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayNavItem } from './TodayNavItem'
import { reportIcon, reportMeta, reportSource, reportTitle } from './todaySignalReports'

function PersonalBriefingNavItems(): JSX.Element {
    const { briefingItems, hoveredItemKey } = useValues(todayLogic)
    const { itemOpened, setHoveredItemKey } = useActions(todayLogic)
    const { location } = useValues(router)
    const currentPath = removeProjectIdIfPresent(location.pathname)

    return (
        <>
            {briefingItems.map((item) => {
                const href = itemHref(item)
                const source = itemSource(item)
                return (
                    <TodayNavItem
                        key={item.key}
                        title={item.label}
                        meta={item.signal || source.label}
                        color={source.color}
                        icon={<TodayIcon icon={source.icon} />}
                        to={href}
                        active={hoveredItemKey === item.key}
                        current={removeProjectIdIfPresent(href) === currentPath}
                        done={item.state === 'done'}
                        dataAttr="today-nav-item"
                        onClick={() => itemOpened(item, 'sidebar')}
                        onHoverChange={(hovered) => setHoveredItemKey(hovered ? item.key : null)}
                    />
                )
            })}
        </>
    )
}

export function TodayHomeSidebar(): JSX.Element {
    const {
        reportId,
        reports,
        topReports,
        reportsFailed,
        hoveredReportId,
        reportSummary,
        inboxMore,
        showPersonalBriefing,
        personalBriefing,
        personalBriefingPending,
    } = useValues(todayLogic)
    const { reportOpened, setHoveredReportId } = useActions(todayLogic)

    const loading = personalBriefingPending || (topReports === null && !reportsFailed)
    const homeMeta = showPersonalBriefing
        ? (personalBriefing?.headline ?? '')
        : loading
          ? 'Reading your project…'
          : topReports === null
            ? 'Reports didn’t load'
            : reportSummary

    return (
        <div className="TodayPane" data-quill>
            <Button
                variant="primary"
                size="lg"
                className="w-full"
                render={<LinkPrimitive to={urls.ai()} />}
                data-attr="today-new-chat"
            >
                <IconPlus />
                New chat
            </Button>
            <div className="TodayPane__scroll">
                <div className="TodayPane__heading Today__label">Today</div>
                <div className="TodaySidebar__list">
                    <TodayNavItem
                        title="Home"
                        meta={homeMeta}
                        color="var(--color-text-secondary)"
                        icon={<IconHome />}
                        to={urls.projectHomepage()}
                        current={reportId === null}
                        dataAttr="today-nav-home"
                    />
                    {showPersonalBriefing ? (
                        <PersonalBriefingNavItems />
                    ) : loading ? (
                        <>
                            <Skeleton className="h-12" />
                            <Skeleton className="h-12" />
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
                {inboxMore && (
                    <Link to={urls.inbox()} className="TodaySidebar__more" data-attr="today-nav-inbox">
                        {inboxMore.scope === 'for_you'
                            ? `${inboxMore.count} more for you in the Inbox`
                            : `${inboxMore.count} more in the Inbox`}
                    </Link>
                )}
            </div>
        </div>
    )
}
