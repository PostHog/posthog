import { useActions, useValues } from 'kea'

import { IconFolder, IconPlusSmall } from '@posthog/icons'
import {
    Button,
    CardGroup,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Empty,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
} from '@posthog/quill'

import { AnalyticsSearchInput } from './AnalyticsSearchInput'
import { analyticsShareLogic } from './analyticsShareLogic'
import { ShareToSpaceBreadcrumbs } from './ShareToSpaceBreadcrumbs'
import { ShareToSpaceDialogRow } from './ShareToSpaceDialogRow'
import { ShareToSpaceNewFolderForm } from './ShareToSpaceNewFolderForm'

/** Picks the collection or folder an item is added or moved to, from the Analytics list or an insight's Share menu. */
export function ShareToSpaceDialog(): JSX.Element {
    const {
        target,
        currentFolder,
        browsePath,
        pickerSearch,
        pickerSearching,
        pickerRows,
        pickerLoading,
        pickerErrorMessage,
        pickerEmptyMessage,
        newFolderOpen,
        moveDisabledReason,
        moveButtonLabel,
        sharing,
    } = useValues(analyticsShareLogic)
    const { closeShareToSpace, browseTo, setPickerSearch, setNewFolderOpen, moveHere } = useActions(analyticsShareLogic)
    const atRoot = browsePath === null
    const showCrumbs = !pickerSearching && !atRoot

    return (
        <Dialog open={!!target} onOpenChange={(open: boolean) => !open && closeShareToSpace()}>
            {/* Wider than the default 24rem so the new-folder button fits across from Cancel and Move. */}
            <DialogContent className="sm:max-w-120" data-attr="analytics-share-dialog">
                <DialogHeader className="gap-3">
                    <DialogTitle>{currentFolder !== null ? 'Move to a collection' : 'Add to a collection'}</DialogTitle>
                    <DialogDescription className="sr-only">
                        {target ? `Pick a collection or folder for "${target.name}".` : ''}
                    </DialogDescription>
                    <AnalyticsSearchInput
                        value={pickerSearch}
                        onChange={setPickerSearch}
                        label="Search collections and folders"
                        placeholder="Search collections and folders"
                        dataAttr="analytics-share-search"
                        className="w-full"
                        autoFocus
                    />
                    {showCrumbs && <ShareToSpaceBreadcrumbs />}
                </DialogHeader>
                {/* A fixed height keeps the dialog from jumping as the user opens folders and searches. The body gives
                    the breadcrumb row's height back when the crumbs are hidden. */}
                <DialogBody className={showCrumbs ? 'h-72' : 'h-80'}>
                    {newFolderOpen && <ShareToSpaceNewFolderForm />}
                    {pickerLoading ? (
                        <div className="flex flex-col gap-2" aria-busy>
                            <Skeleton className="h-11" />
                            <Skeleton className="h-11" />
                            <Skeleton className="h-11" />
                        </div>
                    ) : pickerErrorMessage ? (
                        <Empty className="py-8">
                            <EmptyHeader>
                                <EmptyTitle>{pickerErrorMessage}</EmptyTitle>
                            </EmptyHeader>
                        </Empty>
                    ) : !pickerRows.length ? (
                        <Empty className="py-8">
                            <EmptyHeader>
                                <EmptyMedia variant="icon">
                                    <IconFolder />
                                </EmptyMedia>
                                <EmptyTitle>{pickerEmptyMessage}</EmptyTitle>
                            </EmptyHeader>
                        </Empty>
                    ) : (
                        <CardGroup size="sm">
                            {pickerRows.map((row) => (
                                <ShareToSpaceDialogRow
                                    key={row.path}
                                    row={row}
                                    isCurrent={row.path === currentFolder}
                                    onOpen={browseTo}
                                />
                            ))}
                        </CardGroup>
                    )}
                </DialogBody>
                <DialogFooter className="sm:justify-between">
                    <Button
                        variant="outline"
                        disabledReason={
                            newFolderOpen
                                ? 'Name the new one first'
                                : pickerSearching
                                  ? 'Clear the search first'
                                  : undefined
                        }
                        onClick={() => setNewFolderOpen(true)}
                        data-attr="analytics-share-new-folder"
                    >
                        <IconPlusSmall />
                        {atRoot ? 'New collection' : 'New folder'}
                    </Button>
                    <div className="flex min-w-0 flex-col-reverse gap-2 sm:flex-row">
                        <DialogClose render={<Button variant="outline" data-attr="analytics-share-cancel" />}>
                            Cancel
                        </DialogClose>
                        <Button
                            variant="primary"
                            className="max-w-60"
                            loading={sharing}
                            disabledReason={sharing ? undefined : (moveDisabledReason ?? undefined)}
                            onClick={() => moveHere()}
                            // pinned: data-attr of the button that moves the item. Dashboards count its clicks.
                            data-attr="analytics-share-to-space"
                        >
                            <span className="truncate">{moveButtonLabel}</span>
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
