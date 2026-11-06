import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useMemo, useState } from 'react'
import { useInView } from 'react-intersection-observer'

import {
    IconChevronDown,
    IconFolder,
    IconFolderPlus,
    IconList,
    IconPerson,
    IconPlus,
    IconSearch,
    IconTrash,
} from '@posthog/icons'
import {
    Button,
    Card,
    DataTable,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Spinner,
    Text,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { todayAnalyticsLogic } from '~/layout/today/todayAnalyticsLogic'
import { TodayAnalyticsNewFolderDialog } from '~/layout/today/TodayAnalyticsNewFolderDialog'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { AnalyticsCreateModals } from './AnalyticsCreateModals'
import { analyticsOrderByOfColumn, parseAnalyticsOrderBy } from './analyticsFeed'
import { AnalyticsFolderBreadcrumbs } from './AnalyticsFolderBreadcrumbs'
import { AnalyticsListRow, analyticsListColumns } from './AnalyticsListColumns'
import { AnalyticsListFilters } from './AnalyticsListFilters'
import { analyticsListLogic, analyticsListUrlParams } from './analyticsListLogic'
import { AnalyticsListSkeleton } from './AnalyticsListSkeleton'
import { AnalyticsPinMenuItem } from './AnalyticsPinMenuItem'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'
import { ANALYTICS_DRAG_SCOPE, ANALYTICS_TYPE_INFO, USERS_FOLDER, analyticsSpaceOfPath } from './analyticsUtils'
import { NewAnalyticsMenu } from './NewAnalyticsMenu'
import { ShareToSpaceDialog } from './ShareToSpaceDialog'

const SCROLL_PREFETCH_MARGIN = '1200px 0px'
const EMPTY_COLLECTION: ReactNode = <Text size="sm">Nothing in this collection.</Text>

export const scene: SceneExport = {
    component: AnalyticsList,
    logic: analyticsListLogic,
}

export function AnalyticsList(): JSX.Element {
    const analyticsEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    // The page ships behind the Today navigation, so without the flag `/analytics/all` stays a missing page.
    return analyticsEnabled ? <AnalyticsListContent /> : <NotFound object="page" />
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
        feedQuery,
    } = useValues(analyticsListLogic)
    const { clearFilters, loadList, loadMore, setFilters } = useActions(analyticsListLogic)
    const { setNewFolderDialogOpen } = useActions(todayAnalyticsLogic)
    const { deleteItem } = useActions(projectTreeDataLogic)
    const [tableViewport, setTableViewport] = useState<HTMLDivElement | null>(null)
    const { ref: tableEndRef, inView: tableEndInView } = useInView({
        root: tableViewport,
        rootMargin: SCROLL_PREFETCH_MARGIN,
        skip: !tableViewport,
    })
    // With no table on screen, a filter may have left out every row so far, so the next page may hold the first.
    const nearEnd = !tableViewport || tableEndInView
    // An opened page sends the person back to this exact list, filters included.
    const backUrl =
        scope === 'mine'
            ? urls.analyticsMine(analyticsListUrlParams(filters))
            : urls.analyticsList(analyticsListUrlParams(filters))
    const showSpace = mode === 'feed'
    const showOwner = scope !== 'mine'
    const columns = useMemo(
        () => analyticsListColumns({ backUrl, showSpace, showOwner }),
        [backUrl, showSpace, showOwner]
    )
    const rows = useMemo<AnalyticsListRow[]>(
        () => [
            ...subfolders.map((folder) => ({ kind: 'folder' as const, folder })),
            ...items.map((item) => ({ kind: 'item' as const, item })),
        ],
        [subfolders, items]
    )
    const spaceName = mode === 'folder' ? folderBreadcrumbs[folderBreadcrumbs.length - 1]?.name || 'Project root' : null
    // Only the collection itself is deleted from Manage; a folder inside it is deleted from its row.
    const topLevelSpace = mode === 'folder' && filters.folder ? analyticsSpaceOfPath(filters.folder) : null
    const isSpaceRoot = !!topLevelSpace && topLevelSpace !== USERS_FOLDER && folderBreadcrumbs.length === 1

    useEffect(() => {
        if (nearEnd && hasMore) {
            loadMore()
        }
    }, [nearEnd, hasMore, loadedCount, loadMore])

    const newButton = (
        <NewAnalyticsMenu source="list" trigger={<Button variant="primary" data-attr="analytics-list-new" />}>
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
                            size="sm"
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
            return (
                <Card size="sm" flush className="pt-0">
                    <AnalyticsListSkeleton columns={columns} />
                </Card>
            )
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
                            size="sm"
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
                                ? 'Add something to this collection from its page and it shows up here.'
                                : scope === 'mine'
                                  ? 'Canvases, dashboards, notebooks and insights you create show up here.'
                                  : 'Canvases, dashboards, notebooks and insights show up here as people create them.'}
                        </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        {mode === 'feed' ? (
                            newButton
                        ) : (
                            <Button
                                variant="outline"
                                size="sm"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.analyticsSpaces()} />}
                                data-attr="analytics-list-browse-all"
                            >
                                Back to collections
                            </Button>
                        )}
                    </EmptyContent>
                </Empty>
            )
        }
        return (
            <div
                className={cn('flex min-h-0 flex-col transition-opacity', feedStale && 'opacity-60')}
                aria-busy={feedStale || hasMore}
            >
                {rows.length > 0 && (
                    <Card size="sm" flush className="min-h-0 pt-0">
                        <DataTable
                            columns={columns}
                            data={rows}
                            fullWidth
                            size="sm"
                            stickyHeader
                            resizableColumns
                            viewportRef={setTableViewport}
                            viewportEndRef={tableEndRef}
                            sorting={
                                mode === 'feed' && feedQuery.orderBy ? [parseAnalyticsOrderBy(feedQuery.orderBy)] : []
                            }
                            onSortingChange={([sort]) => {
                                const orderBy = sort && analyticsOrderByOfColumn(sort)
                                if (orderBy) {
                                    setFilters({ orderBy })
                                }
                            }}
                            className="flex min-h-0 flex-col [--quill-table-sticky-bg:var(--card)]"
                            empty={EMPTY_COLLECTION}
                        />
                    </Card>
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
        <SceneContent className="min-h-0 flex-1 pb-4">
            <SceneTitleSection
                name={spaceName ?? (scope === 'mine' ? 'My work' : 'View all')}
                description={
                    mode === 'folder'
                        ? null
                        : scope === 'mine'
                          ? 'Everything you created, shared or not.'
                          : 'Canvases, dashboards, notebooks and insights shared in this project.'
                }
                resourceType={{
                    type: 'analytics',
                    forceIcon: spaceName ? (
                        <AnalyticsSpaceGlyph name={spaceName} />
                    ) : scope === 'mine' ? (
                        <IconPerson />
                    ) : (
                        <IconList />
                    ),
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
                        {isSpaceRoot && topLevelSpace && (
                            <DropdownMenu>
                                <DropdownMenuTrigger
                                    render={<Button variant="outline" size="sm" data-attr="analytics-space-manage" />}
                                >
                                    Manage
                                    <IconChevronDown />
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end" className="min-w-48">
                                    <AnalyticsPinMenuItem
                                        target={{
                                            type: 'folder',
                                            ref: filters.folder!,
                                            name: spaceName ?? topLevelSpace,
                                        }}
                                        dataAttr="analytics-space-pin-manage"
                                    />
                                    <DropdownMenuItem
                                        variant="destructive"
                                        onClick={() =>
                                            deleteItem(
                                                { path: filters.folder!, type: 'folder' } as FileSystemEntry,
                                                ANALYTICS_DRAG_SCOPE
                                            )
                                        }
                                        data-attr="analytics-space-delete"
                                    >
                                        <IconTrash />
                                        Delete collection…
                                    </DropdownMenuItem>
                                </DropdownMenuContent>
                            </DropdownMenu>
                        )}
                        {newButton}
                    </div>
                }
            />
            <div data-quill className="flex min-h-0 flex-1 flex-col gap-3">
                {mode === 'folder' && <AnalyticsFolderBreadcrumbs crumbs={folderBreadcrumbs} />}
                <AnalyticsListFilters />
                {listState === 'ready' && failedTypes.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2" role="alert">
                        <Text size="sm" variant="destructive">
                            {`${new Intl.ListFormat('en', { type: 'conjunction' }).format(
                                failedTypes.map((type) => ANALYTICS_TYPE_INFO[type].pluralLabel)
                            )} didn’t load, so this list may be incomplete.`}
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
            </div>
            <AnalyticsCreateModals />
            <ShareToSpaceDialog />
            <TodayAnalyticsNewFolderDialog />
        </SceneContent>
    )
}
