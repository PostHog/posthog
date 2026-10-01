import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGridMasonry, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'
import { NewViewMenu } from 'scenes/views/NewViewMenu'
import { VIEW_TYPE_INFO } from 'scenes/views/viewsUtils'
import { ViewTypeIcon } from 'scenes/views/ViewTypeIcon'

import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSection } from './TodayPaneSection'
import { todayViewsLogic } from './todayViewsLogic'
import { shortTimeAgo } from './todayWorkItems'

/** The Views sub-nav: a "New" menu, the full list, and the most recent views of every type, newest first. */
export function TodayViewsSidebar(): JSX.Element {
    const { recentViews, recentItems, recentViewsLoading, recentUnavailable, recentCollapsed } =
        useValues(todayViewsLogic)
    const { loadRecentViews, toggleRecent } = useActions(todayViewsLogic)
    const { location } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)
    const failedTypes = recentViews?.failedTypes ?? []

    const retryButton = (size: 'small' | 'xsmall'): JSX.Element => (
        <LemonButton
            size={size}
            type="secondary"
            loading={recentViewsLoading}
            onClick={() => loadRecentViews()}
            data-attr="today-views-retry"
        >
            Try again
        </LemonButton>
    )

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
                <TodayPaneSection
                    label="Recent"
                    open={!recentCollapsed}
                    count={recentItems.length}
                    onToggle={toggleRecent}
                    dataAttr="today-views-section-recent"
                >
                    {!recentViews ? (
                        recentUnavailable ? (
                            <div className="TodayPane__state">
                                <span>Your views didn’t load.</span>
                                {retryButton('small')}
                            </div>
                        ) : (
                            <div className="TodayPane__state" aria-busy>
                                <Spinner />
                            </div>
                        )
                    ) : !recentItems.length && !failedTypes.length && !recentUnavailable ? (
                        <div className="TodayPane__state">
                            Canvases, notebooks and dashboards you create show up here.
                        </div>
                    ) : (
                        <>
                            {(recentUnavailable || failedTypes.length > 0) && (
                                <div className="TodayPane__state">
                                    <span>
                                        {recentUnavailable
                                            ? 'Your views didn’t refresh.'
                                            : `${failedTypes.map((type) => VIEW_TYPE_INFO[type].pluralLabel).join(' and ')} didn’t load.`}
                                    </span>
                                    {retryButton('xsmall')}
                                </div>
                            )}
                            {recentItems.map((item) => (
                                <TodayPaneRow
                                    key={`${item.type}-${item.id}`}
                                    label={item.name}
                                    icon={<ViewTypeIcon type={item.type} />}
                                    meta={shortTimeAgo(item.timestamp)}
                                    to={item.href}
                                    active={path === removeProjectIdIfPresent(item.href)}
                                    dataAttr={`today-views-recent-${item.type}`}
                                />
                            ))}
                        </>
                    )}
                </TodayPaneSection>
            </div>
        </div>
    )
}
