import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { useInView } from 'react-intersection-observer'

import { IconFolder, IconPlus, IconSearch } from '@posthog/icons'
import {
    Button,
    DataTable,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Item,
    ItemContent,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { AnalyticsCreateModals } from './AnalyticsCreateModals'
import { AnalyticsFolderBreadcrumbs } from './AnalyticsFolderBreadcrumbs'
import { analyticsListColumns } from './AnalyticsListColumns'
import { AnalyticsListFilters } from './AnalyticsListFilters'
import { analyticsListLogic, analyticsListUrlParams } from './analyticsListLogic'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPE_INFO } from './analyticsUtils'
import { NewAnalyticsMenu } from './NewAnalyticsMenu'

const SCROLL_PREFETCH_MARGIN = '1200px 0px'

export const scene: SceneExport = {
    component: AnalyticsList,
    logic: analyticsListLogic,
}

export function AnalyticsList(): JSX.Element {
    const analyticsEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    // The page ships behind the Today navigation, so without the flag `/analytics/all` stays a missing page.
    return analyticsEnabled ? <AnalyticsListContent /> : <NotFound object="page" />
}

function TableSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-2" aria-busy aria-label="Loading analytics">
            {Array.from({ length: 6 }, (_, index) => (
                <Skeleton key={index} className="h-9" />
            ))}
        </div>
    )
}

function AnalyticsListContent(): JSX.Element {
    const { filters, items, subfolders, folderBreadcrumbs, listState, loading, hasMore, failedTypes, feedStale, mode } =
        useValues(analyticsListLogic)
    const { clearFilters, loadList, loadMore } = useActions(analyticsListLogic)
    const { ref: endRef, inView: endInView } = useInView({
        root: document.getElementById('main-content'),
        rootMargin: SCROLL_PREFETCH_MARGIN,
    })
    // An opened page sends the person back to this exact list, filters included.
    const backUrl = urls.analyticsList(analyticsListUrlParams(filters))
    const columns = analyticsListColumns({ backUrl, showType: filters.type === 'all' })

    useEffect(() => {
        if (endInView && hasMore) {
            loadMore()
        }
    }, [endInView, hasMore, items.length, loadMore])

    const newButton = (
        <NewAnalyticsMenu source="list" trigger={<Button variant="primary" size="sm" data-attr="analytics-list-new" />}>
            <IconPlus />
            New
        </NewAnalyticsMenu>
    )

    const renderBody = (): JSX.Element => {
        if (listState === 'error') {
            return (
                <Empty>
                    <EmptyHeader>
                        <EmptyTitle>Couldn’t load your analytics</EmptyTitle>
                        <EmptyDescription>Try again, and if it keeps happening contact support.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            loading={loading}
                            onClick={() => loadList()}
                            data-attr="analytics-list-retry"
                        >
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        if (listState === 'loading') {
            return <TableSkeleton />
        }
        if (listState === 'no-matches') {
            return (
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconSearch />
                        </EmptyMedia>
                        <EmptyTitle>Nothing matches these filters</EmptyTitle>
                        <EmptyDescription>Try a different name, or clear the filters.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            onClick={() => clearFilters()}
                            data-attr="analytics-list-clear-filters"
                        >
                            Clear filters
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        if (listState === 'empty') {
            return (
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconFolder />
                        </EmptyMedia>
                        <EmptyTitle>{mode === 'folder' ? 'This folder is empty' : 'No analytics yet'}</EmptyTitle>
                        <EmptyDescription>
                            {mode === 'folder'
                                ? 'Analytics moved into this folder show up here.'
                                : 'Canvases, dashboards, notebooks and insights you create show up here.'}
                        </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        {mode === 'feed' ? (
                            newButton
                        ) : (
                            <Button
                                variant="outline"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.analyticsList()} />}
                                data-attr="analytics-list-browse-all"
                            >
                                Browse all analytics
                            </Button>
                        )}
                    </EmptyContent>
                </Empty>
            )
        }
        return (
            <div
                className={feedStale ? 'opacity-60 transition-opacity' : 'transition-opacity'}
                aria-busy={feedStale || hasMore}
            >
                {subfolders.length > 0 && (
                    <ItemGroup className="mb-3 grid grid-cols-1 gap-2 @md/analytics:grid-cols-3">
                        {subfolders.map((folder) => (
                            <Item
                                key={folder.path}
                                variant="outline"
                                size="sm"
                                className="text-foreground hover:bg-fill-button-tertiary-hover hover:text-foreground"
                                render={
                                    <LinkPrimitive
                                        to={urls.analyticsList({ folder: folder.path })}
                                        data-attr="analytics-list-subfolder"
                                    />
                                }
                            >
                                <ItemMedia variant="icon" aria-hidden>
                                    <IconFolder />
                                </ItemMedia>
                                <ItemContent className="min-w-0">
                                    <ItemTitle className="truncate">{folder.name}</ItemTitle>
                                </ItemContent>
                            </Item>
                        ))}
                    </ItemGroup>
                )}
                {items.length > 0 && (
                    <DataTable
                        columns={columns}
                        data={items}
                        fullWidth
                        size="sm"
                        stickyHeader
                        // The title column soaks up the slack, and `max-w-0` stops a long title from widening
                        // the table past its container, so the filters above keep their width across types.
                        // Below the minimum width the table scrolls sideways instead of squeezing the title away.
                        className="w-full min-w-0 **:data-expand:max-w-0 **:data-[slot=table]:min-w-208"
                        empty={<Text size="sm">No analytics in this folder.</Text>}
                    />
                )}
                {hasMore && (
                    <div className="flex justify-center py-3">
                        <Button
                            variant="outline"
                            size="sm"
                            loading={loading}
                            onClick={() => loadMore()}
                            data-attr="analytics-list-load-more"
                        >
                            Show more
                        </Button>
                    </div>
                )}
            </div>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={mode === 'folder' ? 'Folders' : 'Analytics'}
                description={mode === 'feed' ? 'Canvases, dashboards, notebooks and insights in this project.' : null}
                resourceType={{ type: 'analytics', forceIcon: <AnalyticsTypeIcon type="dashboard" /> }}
                actions={<div data-quill>{newButton}</div>}
            />
            <div data-quill className="@container/analytics flex flex-col gap-3">
                {mode === 'folder' && <AnalyticsFolderBreadcrumbs crumbs={folderBreadcrumbs} />}
                <AnalyticsListFilters />
                {listState === 'ready' && failedTypes.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2" role="alert">
                        <Text size="sm" variant="destructive">
                            {`${failedTypes
                                .map((type) => ANALYTICS_TYPE_INFO[type].pluralLabel)
                                .join(' and ')} didn’t load, so this list may be incomplete.`}
                        </Text>
                        <Button
                            variant="outline"
                            size="xs"
                            loading={loading}
                            onClick={() => loadList()}
                            data-attr="analytics-list-retry"
                        >
                            Try again
                        </Button>
                    </div>
                )}
                {renderBody()}
                <div ref={endRef} aria-hidden />
            </div>
            <AnalyticsCreateModals />
        </SceneContent>
    )
}
