import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGridMasonry, IconPlus, IconSearch } from '@posthog/icons'
import { Button, Spinner, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'
import { NewViewMenu } from 'scenes/views/NewViewMenu'
import { VIEW_TYPE_INFO } from 'scenes/views/viewsUtils'
import { ViewTypeIcon } from 'scenes/views/ViewTypeIcon'

import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSearchField } from './TodayPaneSearchField'
import { TodayPaneSection } from './TodayPaneSection'
import { TodayViewsFilterMenu } from './TodayViewsFilterMenu'
import { todayViewsLogic } from './todayViewsLogic'
import { shortTimeAgo } from './todayWorkItems'

/** The Views sub-nav: a "New" menu, the full list, and the most recent views of every type, newest first. */
export function TodayViewsSidebar(): JSX.Element {
    const {
        recentViews,
        recentItems,
        recentViewsLoading,
        recentUnavailable,
        recentCollapsed,
        recentQuery,
        recentSearchVisible,
        recentFiltersActive,
        buildingViewIds,
    } = useValues(todayViewsLogic)
    const { loadRecentViews, toggleRecent, setRecentQuery, setRecentSearchOpen, clearRecentSearchAndFilters } =
        useActions(todayViewsLogic)
    const narrowed = recentQuery.trim() !== '' || recentFiltersActive
    const { location } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)
    const failedTypes = recentViews?.failedTypes ?? []

    const retryButton = (size: 'sm' | 'xs'): JSX.Element => (
        <Button
            size={size}
            variant="outline"
            loading={recentViewsLoading}
            onClick={() => loadRecentViews()}
            data-attr="today-views-retry"
        >
            Try again
        </Button>
    )

    return (
        <div className="TodayPane" data-quill>
            <NewViewMenu
                trigger={<Button variant="primary" size="lg" className="w-full" data-attr="today-views-new" />}
            >
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
                    heading={
                        recentSearchVisible ? (
                            <TodayPaneSearchField
                                query={recentQuery}
                                resultCount={recentItems.length}
                                label="Search views"
                                onQueryChange={setRecentQuery}
                                onClose={() => setRecentSearchOpen(false)}
                                dataAttr="today-views-search"
                            />
                        ) : null
                    }
                    actions={
                        <>
                            {!recentSearchVisible && (
                                <Tooltip>
                                    <TooltipTrigger
                                        delay={0}
                                        render={
                                            <Button
                                                size="icon-xs"
                                                className="text-muted-foreground"
                                                aria-label="Search views"
                                                onClick={() => setRecentSearchOpen(true)}
                                                data-attr="today-views-search-open"
                                            />
                                        }
                                    >
                                        <IconSearch />
                                    </TooltipTrigger>
                                    <TooltipContent>Search views</TooltipContent>
                                </Tooltip>
                            )}
                            <TodayViewsFilterMenu />
                        </>
                    }
                >
                    {!recentViews || (recentViewsLoading && !recentItems.length) ? (
                        recentUnavailable ? (
                            <div className="TodayPane__state">
                                <span>Your views didn’t load.</span>
                                {retryButton('sm')}
                            </div>
                        ) : (
                            <div className="TodayPane__state" aria-busy>
                                <Spinner />
                            </div>
                        )
                    ) : !recentItems.length && narrowed ? (
                        <div className="TodayPane__state">
                            <span>Nothing here matches.</span>
                            <Button
                                size="xs"
                                variant="outline"
                                onClick={() => clearRecentSearchAndFilters()}
                                data-attr="today-views-clear-filters"
                            >
                                Clear filters
                            </Button>
                        </div>
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
                                    {retryButton('xs')}
                                </div>
                            )}
                            {recentViews.truncated && (
                                <div className="TodayPane__state">
                                    Some views are not shown. Open All views and use search to find them.
                                </div>
                            )}
                            {recentViewsLoading && (
                                <div className="TodayPane__state" role="status">
                                    Loading more views…
                                </div>
                            )}
                            {recentItems.map((item) => {
                                const building = buildingViewIds.includes(item.id)
                                return (
                                    <TodayPaneRow
                                        key={`${item.type}-${item.id}`}
                                        label={item.name}
                                        icon={building ? <Spinner /> : <ViewTypeIcon type={item.type} />}
                                        meta={building ? 'Building' : shortTimeAgo(item.timestamp)}
                                        to={item.href}
                                        active={path === removeProjectIdIfPresent(item.href)}
                                        dataAttr={`today-views-recent-${item.type}`}
                                    />
                                )
                            })}
                        </>
                    )}
                </TodayPaneSection>
            </div>
        </div>
    )
}
