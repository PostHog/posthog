import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconHome, IconPlus } from '@posthog/icons'
import { Button, MenuLabel, Skeleton } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'

import { displayConventionalCommitTitle } from 'products/signals/frontend/inbox/utils/reportPresentation'

import { isExternalHref, itemHref, itemSource, itemStateLabel } from './todayBriefingItems'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayMoreReports } from './TodayMoreReports'
import { TodayNavItem } from './TodayNavItem'
import { TodayReportNavItem } from './TodayReportNavItem'

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
                        title={displayConventionalCommitTitle(item.title, 'Untitled report')}
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
        reportSummary,
        showPersonalBriefing,
        personalBriefing,
        teamReportPreviews,
    } = useValues(todayLogic)

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
                elevated
                variant="outline"
                size="lg"
                className="mb-1 w-full"
                nativeButton={false}
                render={<LinkPrimitive to={urls.taskNewSession()} />}
                data-attr="today-new-chat"
            >
                <IconPlus />
                New session
            </Button>
            <div className="TodayPane__scroll">
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
                    {(loading || showPersonalBriefing || reports.length > 0) && (
                        <MenuLabel className="mt-3">{showPersonalBriefing ? 'Your briefing' : 'Reports'}</MenuLabel>
                    )}
                    {showPersonalBriefing ? (
                        <PersonalBriefingNavItems />
                    ) : loading ? (
                        <>
                            <Skeleton className="h-13" />
                            <Skeleton className="h-13" />
                        </>
                    ) : (
                        reports.map((report) => (
                            <TodayReportNavItem
                                key={report.id}
                                report={report}
                                preview={teamReportPreviews.sidebar[report.id]}
                                source="sidebar"
                                dataAttr="today-nav-report"
                            />
                        ))
                    )}
                    <TodayMoreReports />
                </div>
            </div>
        </div>
    )
}
