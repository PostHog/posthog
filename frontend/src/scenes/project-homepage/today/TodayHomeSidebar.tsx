import { useActions, useValues } from 'kea'

import { IconHome, IconPlus } from '@posthog/icons'
import {
    Button,
    NavItem,
    NavItemButton,
    NavItemContent,
    NavItemDescription,
    NavItemLabel,
    Skeleton,
    cn,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodayPane } from '~/layout/today/TodayPane'
import { TodayPaneGroup } from '~/layout/today/TodayPaneGroup'

import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { reportIcon, reportMeta, reportTitle } from './todaySignalReports'

export function TodayHomeSidebar(): JSX.Element {
    const { reportId, reports, topReports, reportsFailed, hoveredReportId, reportSummary, moreReportCount } =
        useValues(todayLogic)
    const { reportOpened, setHoveredReportId } = useActions(todayLogic)

    return (
        <TodayPane
            label="Today"
            header={
                <Button
                    variant="primary"
                    className="w-full"
                    render={<LinkPrimitive to={urls.ai()} />}
                    data-attr="today-new-chat"
                >
                    <IconPlus />
                    New chat
                </Button>
            }
        >
            <TodayPaneGroup label="Today">
                <NavItem>
                    <NavItemButton
                        current={reportId === null}
                        render={<LinkPrimitive to={urls.projectHomepage()} />}
                        data-attr="today-nav-home"
                    >
                        <IconHome />
                        <NavItemContent>
                            <NavItemLabel>Home</NavItemLabel>
                            <NavItemDescription>
                                {topReports === null
                                    ? reportsFailed
                                        ? 'Reports didn’t load'
                                        : 'Reading your project…'
                                    : reportSummary}
                            </NavItemDescription>
                        </NavItemContent>
                    </NavItemButton>
                </NavItem>
                {topReports === null && !reportsFailed ? (
                    <>
                        <Skeleton className="h-10" />
                        <Skeleton className="h-10" />
                    </>
                ) : (
                    reports.map((report) => (
                        <NavItem key={report.id}>
                            <NavItemButton
                                current={reportId === report.id}
                                // The briefing's hovered report link lights up its row here too.
                                className={cn(hoveredReportId === report.id && 'bg-fill-hover')}
                                render={<LinkPrimitive to={urls.todayReport(report.id)} />}
                                data-attr="today-nav-report"
                                onClick={() => reportOpened(report, 'sidebar')}
                                onMouseEnter={() => setHoveredReportId(report.id)}
                                onMouseLeave={() => setHoveredReportId(null)}
                            >
                                <TodayIcon icon={reportIcon(report)} />
                                <NavItemContent>
                                    <NavItemLabel>{reportTitle(report)}</NavItemLabel>
                                    <NavItemDescription>{reportMeta(report)}</NavItemDescription>
                                </NavItemContent>
                            </NavItemButton>
                        </NavItem>
                    ))
                )}
            </TodayPaneGroup>
            {moreReportCount > 0 && (
                <Button
                    variant="link-muted"
                    size="sm"
                    className="self-start"
                    render={<LinkPrimitive to={urls.inbox()} />}
                    data-attr="today-nav-inbox"
                >
                    {`${moreReportCount} more in the Inbox`}
                </Button>
            )}
        </TodayPane>
    )
}
