import { useActions, useValues } from 'kea'

import { IconHome, IconPlus } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayNavItem } from './TodayNavItem'
import { reportIcon, reportMeta, reportSource, reportTitle } from './todaySignalReports'

export function TodayHomeSidebar(): JSX.Element {
    const { reportId, reports, topReports, reportsFailed, hoveredReportId, reportSummary, moreReportCount } =
        useValues(todayLogic)
    const { reportOpened, setHoveredReportId } = useActions(todayLogic)

    return (
        <div className="TodaySidebar">
            <LemonButton type="primary" fullWidth center icon={<IconPlus />} to={urls.ai()} data-attr="today-new-chat">
                New chat
            </LemonButton>
            <div className="TodaySidebar__scroll">
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
