import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGridMasonry, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'
import { NewViewMenu } from 'scenes/views/NewViewMenu'
import { VIEW_TYPES } from 'scenes/views/viewsUtils'
import { ViewTypeIcon } from 'scenes/views/ViewTypeIcon'

import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSection } from './TodayPaneSection'
import { todayViewsLogic } from './todayViewsLogic'
import { shortTimeAgo } from './todayWorkItems'

/** The Views sub-nav: a "New" menu, the full list, and the most recent canvases, notebooks and dashboards. */
export function TodayViewsSidebar(): JSX.Element {
    const { recentViews, recentByType, recentViewsLoading, recentUnavailable, collapsedSections } =
        useValues(todayViewsLogic)
    const { loadRecentViews, toggleSection } = useActions(todayViewsLogic)
    const { location } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)
    const failedTypes = recentViews?.failedTypes ?? []

    return (
        <div className="TodayPane">
            <NewViewMenu trigger={<button type="button" className="TodaySidebar__new" data-attr="today-views-new" />}>
                <IconPlus />
                New…
            </NewViewMenu>
            <div className="TodayPane__scroll">
                <TodayPaneRow
                    label="All views"
                    icon={<IconGridMasonry />}
                    to={urls.views()}
                    active={path === urls.views()}
                    dataAttr="today-views-all"
                />
                {VIEW_TYPES.map((info, index) => {
                    const items = recentByType[info.type]
                    return (
                        <TodayPaneSection
                            key={info.type}
                            label={info.pluralLabel}
                            open={!collapsedSections.includes(info.type)}
                            count={items.length}
                            onToggle={() => toggleSection(info.type)}
                            divider={index > 0}
                            dataAttr={`today-views-section-${info.type}`}
                        >
                            {!recentViews && recentViewsLoading ? (
                                <div className="TodayPane__state">
                                    <Spinner />
                                </div>
                            ) : recentUnavailable || failedTypes.includes(info.type) ? (
                                <div className="TodayPane__state">
                                    <span>{info.pluralLabel} didn’t load.</span>
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        loading={recentViewsLoading}
                                        onClick={() => loadRecentViews()}
                                        data-attr="today-views-retry"
                                    >
                                        Try again
                                    </LemonButton>
                                </div>
                            ) : !items.length ? (
                                <div className="TodayPane__state">{`${info.pluralLabel} you create show up here.`}</div>
                            ) : (
                                items.map((item) => (
                                    <TodayPaneRow
                                        key={item.id}
                                        label={item.name}
                                        icon={<ViewTypeIcon type={item.type} />}
                                        meta={shortTimeAgo(item.timestamp)}
                                        to={item.href}
                                        active={path === removeProjectIdIfPresent(item.href)}
                                        dataAttr={`today-views-recent-${item.type}`}
                                    />
                                ))
                            )}
                        </TodayPaneSection>
                    )
                })}
            </div>
        </div>
    )
}
