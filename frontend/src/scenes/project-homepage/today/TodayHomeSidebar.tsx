import { useActions, useValues } from 'kea'

import { IconCheck, IconPlus } from '@posthog/icons'
import { LemonDialog } from '@posthog/lemon-ui'

import { TodayIcon } from './TodayIcon'
import { SCENARIO_COLORS, todayLogic } from './todayLogic'
import { TodayNavItem } from './TodayNavItem'

export function TodayHomeSidebar(): JSX.Element {
    const {
        route,
        visibleReports,
        hoveredReportId,
        reportSummary,
        conversations,
        todayItems,
        loadedMore,
        reports,
        reportsReady,
    } = useValues(todayLogic)
    const { openHome, openNew, openReport, openConversation, setHoveredReportId, removeReport, loadMore } =
        useActions(todayLogic)
    const hasSecondaryReports = reports.some((report) => report.secondary)
    const onHome = route.view === 'home'

    const confirmLoadMore = (): void => {
        LemonDialog.open({
            title: 'Are you sure you want to load more?',
            description: 'A long list of things that need your attention can cause decision paralysis.',
            primaryButton: { children: 'Yes', onClick: loadMore, 'data-attr': 'today-load-more-confirm' },
            secondaryButton: { children: 'No' },
        })
    }

    return (
        <div className="TodaySidebar">
            <button type="button" className="TodaySidebar__new" data-attr="today-new" onClick={openNew}>
                <IconPlus />
                New
            </button>
            <div className="TodaySidebar__scroll">
                <div className="TodaySidebar__sectionLabel Today__label">Today</div>
                <div className="TodaySidebar__list">
                    <TodayNavItem
                        title="Home"
                        meta={reportsReady ? reportSummary : 'Reading your project…'}
                        color="#5c5c57"
                        icon={<TodayIcon report="home" />}
                        current={onHome}
                        dataAttr="today-nav-home"
                        onClick={openHome}
                    />
                    {todayItems.map((item) => (
                        <TodayNavItem
                            key={item.evidenceId}
                            title={item.title}
                            meta={`${item.action} · ready`}
                            color={item.color}
                            icon={<TodayIcon scenario={item.scenarioId} />}
                            current={route.view === 'new' && route.evidenceId === item.evidenceId}
                            entering
                            onClick={() => openConversation(item.conversationId, item.evidenceId)}
                        />
                    ))}
                    {conversations.map((conversation) => (
                        <TodayNavItem
                            key={conversation.id}
                            title={conversation.question}
                            meta={
                                conversation.status === 'thinking'
                                    ? 'Thinking it through…'
                                    : 'Working theory · just now'
                            }
                            color={SCENARIO_COLORS[conversation.scenarioId]}
                            icon={<TodayIcon scenario={conversation.scenarioId} />}
                            thinking={conversation.status === 'thinking'}
                            current={
                                route.view === 'new' && route.conversationId === conversation.id && !route.evidenceId
                            }
                            entering
                            onClick={() => openConversation(conversation.id)}
                        />
                    ))}
                    {reportsReady &&
                        visibleReports.map((report) => (
                            <TodayNavItem
                                key={report.id}
                                title={report.title}
                                meta={report.meta}
                                color={report.color}
                                icon={<TodayIcon report={report.icon} />}
                                active={!report.secondary && hoveredReportId === report.id}
                                current={route.reportId === report.id}
                                complete={report.completed}
                                dataAttr="today-nav-report"
                                onClick={() => openReport(report.id)}
                                onHoverChange={
                                    report.secondary
                                        ? undefined
                                        : (hovered) => setHoveredReportId(hovered ? report.id : null)
                                }
                                onRemove={() => removeReport(report.id)}
                            />
                        ))}
                </div>
                {hasSecondaryReports && (
                    <button
                        type="button"
                        className="TodaySidebar__loadMore"
                        disabled={loadedMore}
                        data-attr="today-load-more"
                        onClick={confirmLoadMore}
                    >
                        {loadedMore ? <IconCheck /> : <IconPlus />}
                        {loadedMore ? 'All items loaded' : 'Load more'}
                    </button>
                )}
            </div>
        </div>
    )
}
