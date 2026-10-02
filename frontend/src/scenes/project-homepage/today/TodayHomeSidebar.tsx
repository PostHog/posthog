import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconHome, IconPlus } from '@posthog/icons'
import { Button, Skeleton } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'

import { isExternalHref, itemHref, itemSource, itemStateLabel } from './todayBriefingItems'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayNavItem } from './TodayNavItem'
import { reportIcon, reportMeta, reportSource, reportTitle } from './todaySignalReports'

function PersonalBriefingNavItems(): JSX.Element {
    const { briefingItems, reportPreviews, hoveredItemKey } = useValues(todayLogic)
    const { itemOpened, setHoveredItemKey } = useActions(todayLogic)
    const { location } = useValues(router)
    const currentPath = removeProjectIdIfPresent(location.pathname)

    return (
        <>
            {briefingItems.map((item) => {
                const href = itemHref(item)
                const source = itemSource(item)
                const preview = reportPreviews.sidebar[item.key]
                const row = (
                    <TodayNavItem
                        key={item.key}
                        title={item.label}
                        meta={itemStateLabel(item) ?? (item.signal || source.label)}
                        color={source.color}
                        icon={<TodayIcon icon={source.icon} />}
                        to={href}
                        target={isExternalHref(href) ? '_blank' : undefined}
                        active={hoveredItemKey === item.key}
                        current={removeProjectIdIfPresent(href) === currentPath}
                        state={item.state}
                        dataAttr="today-nav-item"
                        onClick={() => itemOpened(item, 'sidebar')}
                        onHoverChange={(hovered) => setHoveredItemKey(hovered ? item.key : null)}
                    />
                )
                return preview ? (
                    <TodayPreviewTrigger key={item.key} payload={preview}>
                        {row}
                    </TodayPreviewTrigger>
                ) : (
                    row
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
        showPersonalBriefing,
        personalBriefing,
        teamReportPreviews,
        reportStateOverrides,
    } = useValues(todayLogic)
    const { reportOpened, setHoveredReportId } = useActions(todayLogic)

    // The team reports stand in until the personal briefing is written, so only their own load counts.
    const loading = topReports === null && !reportsFailed
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
                render={<LinkPrimitive to={urls.taskNewSession()} />}
                data-attr="today-new-chat"
            >
                <IconPlus />
                New session
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
                            <TodayPreviewTrigger key={report.id} payload={teamReportPreviews.sidebar[report.id]}>
                                <TodayNavItem
                                    title={reportTitle(report)}
                                    meta={
                                        itemStateLabel({ state: reportStateOverrides[report.id] ?? 'open' }) ??
                                        reportMeta(report)
                                    }
                                    color={reportSource(report).color}
                                    icon={<TodayIcon icon={reportIcon(report)} />}
                                    to={urls.todayReport(report.id)}
                                    active={hoveredReportId === report.id}
                                    current={reportId === report.id}
                                    state={reportStateOverrides[report.id]}
                                    dataAttr="today-nav-report"
                                    onClick={() => reportOpened(report, 'sidebar')}
                                    onHoverChange={(hovered) => setHoveredReportId(hovered ? report.id : null)}
                                />
                            </TodayPreviewTrigger>
                        ))
                    )}
                </div>
            </div>
        </div>
    )
}
