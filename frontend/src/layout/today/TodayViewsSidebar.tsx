import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGridMasonry } from '@posthog/icons'
import { Button, Spinner } from '@posthog/quill'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'
import { VIEW_TYPE_INFO } from 'scenes/views/viewsUtils'
import { ViewTypeIcon } from 'scenes/views/ViewTypeIcon'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { TodayPaneGroupLabel } from './TodayPaneGroupLabel'
import { TodayPaneRow } from './TodayPaneRow'
import { matchesPaneQuery } from './todayPaneSearch'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayViewsFilterMenu } from './TodayViewsFilterMenu'
import { todayViewsLogic } from './todayViewsLogic'
import { shortTimeAgo } from './todayWorkItems'

/** The Views sub-nav: recently viewed views, then the full list, newest first. */
export function TodayViewsSidebar(): JSX.Element {
    const {
        recentViews,
        recentReady,
        recentItems,
        recentViewsLoading,
        recentUnavailable,
        recentQuery,
        recentFiltersActive,
        buildingViewIds,
        recentlyViewed: recents,
    } = useValues(todayViewsLogic)
    const { loadRecentViews, setRecentQuery, clearRecentSearchAndFilters } = useActions(todayViewsLogic)
    const narrowed = recentQuery.trim() !== '' || recentFiltersActive
    const { location } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)
    const failedTypes = recentViews.failedTypes
    const showAll = matchesPaneQuery('All views', recentQuery)

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
            <TodayPaneSearchList
                query={recentQuery}
                onQueryChange={setRecentQuery}
                searchLabel="Search views"
                dataAttr="today-views-search"
                searchActions={<TodayViewsFilterMenu />}
            >
                {recents.length > 0 && (
                    <div>
                        <TodayPaneGroupLabel first>Recently viewed</TodayPaneGroupLabel>
                        {recents.map((recent) => (
                            <TodayPaneRow
                                key={recent.entry.id}
                                value={`recent:${recent.entry.id}`}
                                label={recent.name}
                                icon={iconForType(recent.entry.type as FileSystemIconType)}
                                to={recent.href}
                                active={path === removeProjectIdIfPresent(recent.href)}
                                dataAttr="today-views-recently-viewed"
                            />
                        ))}
                    </div>
                )}
                <div>
                    <TodayPaneGroupLabel first={!recents.length}>Views</TodayPaneGroupLabel>
                    {showAll && (
                        <TodayPaneRow
                            value="all"
                            label="All views"
                            icon={<IconGridMasonry />}
                            to={urls.views()}
                            active={path === urls.views()}
                            dataAttr="today-views-all"
                        />
                    )}
                    {recentUnavailable || !recentReady ? (
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
                    ) : !recentItems.length && !failedTypes.length ? (
                        <div className="TodayPane__state">
                            Canvases, notebooks and dashboards you create show up here.
                        </div>
                    ) : (
                        <>
                            {failedTypes.length > 0 && (
                                <div className="TodayPane__state">
                                    <span>
                                        {`${failedTypes.map((type) => VIEW_TYPE_INFO[type].pluralLabel).join(' and ')} didn’t load.`}
                                    </span>
                                    {retryButton('xs')}
                                </div>
                            )}
                            {recentItems.map((item) => {
                                const building = buildingViewIds.includes(item.id)
                                return (
                                    <TodayPaneRow
                                        key={`${item.type}-${item.id}`}
                                        value={`view:${item.type}-${item.id}`}
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
                </div>
            </TodayPaneSearchList>
        </div>
    )
}
