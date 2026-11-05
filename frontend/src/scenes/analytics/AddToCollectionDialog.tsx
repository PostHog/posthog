import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Empty,
    EmptyContent,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    ItemGroup,
    Skeleton,
    Tabs,
    TabsList,
    TabsTrigger,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { AddToCollectionDialogRow } from './AddToCollectionDialogRow'
import { AddToCollectionTab, addToCollectionItemKey, addToCollectionLogic, isInFolder } from './addToCollectionLogic'
import { AddToCollectionMoveWarning } from './AddToCollectionMoveWarning'
import { AnalyticsSearchInput } from './AnalyticsSearchInput'

/** Picks existing work, the person's own first, and adds it to the collection or folder that is open. */
export function AddToCollectionDialog(): JSX.Element {
    const { folder, folderName, tab, search, feedQuery, feed, selected, selectedCount, adding, addDisabledReason } =
        useValues(addToCollectionLogic)
    const { closeAddToCollection, setTab, setSearch, loadMore, toggleItem, requestAdd, refreshFeed } =
        useActions(addToCollectionLogic)

    const renderBody = (): JSX.Element => {
        if (!feed.initialized) {
            return (
                <div className="flex flex-col gap-2" aria-busy>
                    <Skeleton className="h-11" />
                    <Skeleton className="h-11" />
                    <Skeleton className="h-11" />
                </div>
            )
        }
        if (feed.loadFailed) {
            return (
                <Empty className="py-8">
                    <EmptyHeader>
                        <EmptyTitle>Couldn’t load your items</EmptyTitle>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            onClick={() => refreshFeed(feedQuery)}
                            data-attr="analytics-add-items-retry"
                        >
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        if (!feed.items.length) {
            return (
                <Empty className="py-8">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconFolder />
                        </EmptyMedia>
                        <EmptyTitle>
                            {search.trim()
                                ? 'Nothing matches that search'
                                : tab === 'mine'
                                  ? 'Nothing of yours yet. Check View all for work others made.'
                                  : 'No canvases, dashboards, notebooks or insights yet'}
                        </EmptyTitle>
                    </EmptyHeader>
                </Empty>
            )
        }
        return (
            <div className="flex flex-col gap-2">
                <ItemGroup className="gap-px">
                    {feed.items.map((item) => (
                        <AddToCollectionDialogRow
                            key={addToCollectionItemKey(item)}
                            item={item}
                            checked={!!selected[addToCollectionItemKey(item)]}
                            alreadyHere={isInFolder(item, folder)}
                            onToggle={toggleItem}
                        />
                    ))}
                </ItemGroup>
                {feed.hasMore && (
                    <Button
                        variant="outline"
                        className="self-center"
                        loading={feed.loading}
                        onClick={() => loadMore()}
                        data-attr="analytics-add-items-load-more"
                    >
                        Show more
                    </Button>
                )}
            </div>
        )
    }

    return (
        <Dialog open={!!folder} onOpenChange={(open: boolean) => !open && closeAddToCollection()}>
            <DialogContent className="sm:max-w-120" data-attr="analytics-add-items-dialog">
                <DialogHeader className="gap-3">
                    <DialogTitle>Add to {folderName}</DialogTitle>
                    <DialogDescription className="sr-only">
                        Pick canvases, dashboards, notebooks and insights to move into {folderName}.
                    </DialogDescription>
                    <div className="flex items-center gap-2">
                        <AnalyticsSearchInput
                            value={search}
                            onChange={setSearch}
                            label="Search canvases, dashboards, notebooks and insights"
                            placeholder="Search"
                            dataAttr="analytics-add-items-search"
                            className="min-w-0 flex-1"
                            autoFocus
                        />
                        <Tabs value={tab} onValueChange={(value: AddToCollectionTab) => setTab(value)}>
                            <TabsList>
                                <TabsTrigger value="mine" data-attr="analytics-add-items-tab-mine">
                                    My work
                                </TabsTrigger>
                                <TabsTrigger value="all" data-attr="analytics-add-items-tab-all">
                                    View all
                                </TabsTrigger>
                            </TabsList>
                        </Tabs>
                    </div>
                </DialogHeader>
                {/* A fixed height keeps the dialog from jumping as the person switches tabs and searches. */}
                <DialogBody className="h-80">{renderBody()}</DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" data-attr="analytics-add-items-cancel" />}>
                        Cancel
                    </DialogClose>
                    <Button
                        variant="primary"
                        loading={adding}
                        disabledReason={adding ? undefined : (addDisabledReason ?? undefined)}
                        onClick={() => requestAdd()}
                        data-attr="analytics-add-items-submit"
                    >
                        {selectedCount ? `Add ${pluralize(selectedCount, 'item')}` : 'Add items'}
                    </Button>
                </DialogFooter>
            </DialogContent>
            <AddToCollectionMoveWarning />
        </Dialog>
    )
}
