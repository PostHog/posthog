import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { useInView } from 'react-intersection-observer'

import { IconFolder, IconFolderPlus, IconPlus, IconSearch, IconTrends } from '@posthog/icons'
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
    Spinner,
    Text,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { todayAnalyticsLogic } from '~/layout/today/todayAnalyticsLogic'
import { TodayAnalyticsNewFolderDialog } from '~/layout/today/TodayAnalyticsNewFolderDialog'

import { AnalyticsCreateModals } from './AnalyticsCreateModals'
import { AnalyticsFolderBreadcrumbs } from './AnalyticsFolderBreadcrumbs'
import { analyticsListColumns } from './AnalyticsListColumns'
import { AnalyticsListFilters } from './AnalyticsListFilters'
import { analyticsListLogic, analyticsListUrlParams } from './analyticsListLogic'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'
import { ANALYTICS_TYPE_INFO } from './analyticsUtils'
import { NewAnalyticsMenu } from './NewAnalyticsMenu'
import { ShareToSpaceModal } from './ShareToSpaceModal'

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
    const {
        filters,
        items,
        subfolders,
        folderBreadcrumbs,
        listState,
        loading,
        hasMore,
        failedTypes,
        feedStale,
        mode,
        scope,
        loadedCount,
    } = useValues(analyticsListLogic)
    const { clearFilters, loadList, loadMore } = useActions(analyticsListLogic)
    const { setNewFolderDialogOpen } = useActions(todayAnalyticsLogic)
    const { ref: endRef, inView: endInView } = useInView({
        root: document.getElementById('main-content'),
        rootMargin: SCROLL_PREFETCH_MARGIN,
    })
    // An opened page sends the person back to this exact list, filters included.
    const backUrl =
        scope === 'mine'
            ? urls.analyticsMine(analyticsListUrlParams(filters))
            : urls.analyticsList(analyticsListUrlParams(filters))
    const columns = analyticsListColumns({ backUrl, showSpace: mode === 'feed' })
    const spaceName = mode === 'folder' ? folderBreadcrumbs[folderBreadcrumbs.length - 1]?.name || 'Project root' : null

    useEffect(() => {
        if (endInView && hasMore) {
            loadMore()
        }
    }, [endInView, hasMore, loadedCount, loadMore])

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
                        <EmptyTitle>
                            {mode === 'folder'
                                ? 'Nothing shared here yet'
                                : scope === 'mine'
                                  ? 'Nothing of yours yet'
                                  : 'No analytics yet'}
                        </EmptyTitle>
                        <EmptyDescription>
                            {mode === 'folder'
                                ? 'Share something into this space from its page and it shows up here.'
                                : scope === 'mine'
                                  ? 'Canvases, dashboards, notebooks and insights you create show up here.'
                                  : 'Analytics shared into a space show up here. Yours stay personal until you share them.'}
                        </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        {mode === 'feed' ? (
                            newButton
                        ) : (
                            <Button
                                variant="outline"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.analyticsSpaces()} />}
                                data-attr="analytics-list-browse-all"
                            >
                                Back to spaces
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
                        empty={<Text size="sm">Nothing in this space.</Text>}
                    />
                )}
                {hasMore && (
                    <div className="flex items-center justify-center gap-2 py-3" aria-busy>
                        <Spinner />
                        <Text size="xs" variant="muted">
                            Loading more…
                        </Text>
                    </div>
                )}
            </div>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={spaceName ?? (scope === 'mine' ? 'My analyses' : 'Analytics')}
                description={
                    mode === 'folder'
                        ? null
                        : scope === 'mine'
                          ? 'Everything you created, shared or not.'
                          : 'Canvases, dashboards, notebooks and insights shared in this project.'
                }
                resourceType={{
                    type: 'analytics',
                    forceIcon: spaceName ? <AnalyticsSpaceGlyph name={spaceName} /> : <IconTrends />,
                }}
                actions={
                    <div data-quill className="flex items-center gap-2">
                        {mode === 'folder' && filters.folder && (
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setNewFolderDialogOpen(true, filters.folder)}
                                data-attr="analytics-list-new-folder"
                            >
                                <IconFolderPlus />
                                New folder
                            </Button>
                        )}
                        {newButton}
                    </div>
                }
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
            <ShareToSpaceModal />
            <TodayAnalyticsNewFolderDialog />
        </SceneContent>
    )
}
