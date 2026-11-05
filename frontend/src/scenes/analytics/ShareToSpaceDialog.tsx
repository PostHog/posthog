import { useActions, useValues } from 'kea'

import { IconChevronRight, IconFolder, IconPlusSmall, IconX } from '@posthog/icons'
import {
    Button,
    Card,
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
    Field,
    FieldLabel,
    Input,
    Skeleton,
    Text,
} from '@posthog/quill'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import { AnalyticsSearchInput } from './AnalyticsSearchInput'
import { FolderContentsEntry, analyticsShareLogic } from './analyticsShareLogic'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'

interface PickerRow extends FolderContentsEntry {
    description?: string
}

const ROW_CLASS = 'flex w-full items-center gap-2 px-3 py-2 text-left'
const OPENABLE_ROW_CLASS = `${ROW_CLASS} hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`

/** Picks the collection or folder an item is added or moved to, from the Analytics list or an insight's Share menu. */
export function ShareToSpaceDialog(): JSX.Element {
    const {
        target,
        spaces,
        spacesLoading,
        currentFolder,
        entryLoading,
        browsePath,
        browseCrumbs,
        folderContents,
        folderContentsLoading,
        folderContentsFailed,
        pickerSearch,
        searchResults,
        searchResultsLoading,
        newFolderOpen,
        newFolderName,
        creatingFolder,
        moveDisabledReason,
        sharing,
    } = useValues(analyticsShareLogic)
    const { closeShareToSpace, browseTo, setPickerSearch, setNewFolderOpen, setNewFolderName, createFolder, moveHere } =
        useActions(analyticsShareLogic)
    const moving = currentFolder !== null
    const searching = pickerSearch.trim() !== ''
    const atRoot = browsePath === null
    const destinationName = browseCrumbs.at(-1)?.name

    const rows: PickerRow[] = searching
        ? searchResults.map((result) => ({
              ...result,
              kind: 'folder',
              description: splitPath(result.path).slice(0, -1).join(' / ') || undefined,
          }))
        : atRoot
          ? spaces.map((space) => ({
                path: space.path,
                name: space.name,
                kind: 'folder',
                description: space.total === 0 ? 'Empty' : `${space.total} ${space.total === 1 ? 'item' : 'items'}`,
            }))
          : folderContents
    const loading =
        entryLoading ||
        (searching ? searchResultsLoading : atRoot ? spacesLoading && !spaces.length : folderContentsLoading)
    const failed = !searching && !atRoot && folderContentsFailed
    const emptyMessage = searching
        ? `No collections or folders match "${pickerSearch.trim()}"`
        : atRoot
          ? 'No collections yet'
          : browseCrumbs.length === 1
            ? 'No items in this collection yet'
            : 'No items in this folder yet'

    return (
        <Dialog open={!!target} onOpenChange={(open: boolean) => !open && closeShareToSpace()}>
            {/* Wider than the default 24rem so the new-folder button fits across from Cancel and Move. */}
            <DialogContent className="sm:max-w-120" data-attr="analytics-share-dialog">
                <DialogHeader className="gap-3">
                    <DialogTitle>{moving ? 'Move to a collection' : 'Add to a collection'}</DialogTitle>
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
                    {!searching && !atRoot && (
                        <nav aria-label="Location" className="-mb-1 flex flex-wrap items-center gap-1 text-sm">
                            <Button
                                variant="link-muted"
                                size="sm"
                                className="-ml-2"
                                onClick={() => browseTo(null)}
                                data-attr="analytics-share-crumb-root"
                            >
                                All collections
                            </Button>
                            {browseCrumbs.map((crumb, index) => (
                                <span key={crumb.path} className="flex items-center gap-1">
                                    <IconChevronRight className="size-3 text-muted-foreground" aria-hidden />
                                    {index === browseCrumbs.length - 1 ? (
                                        <Text size="sm" className="px-2 font-semibold">
                                            {crumb.name}
                                        </Text>
                                    ) : (
                                        <Button
                                            variant="link-muted"
                                            size="sm"
                                            onClick={() => browseTo(crumb.path)}
                                            data-attr="analytics-share-crumb"
                                        >
                                            {crumb.name}
                                        </Button>
                                    )}
                                </span>
                            ))}
                        </nav>
                    )}
                </DialogHeader>
                {/* A fixed height keeps the dialog from jumping as the user opens folders and searches. The body gives
                    the breadcrumb row's height back when the crumbs are hidden. */}
                <DialogBody className={searching || atRoot ? 'h-80' : 'h-72'}>
                    {newFolderOpen && (
                        <Card size="sm" className="relative mb-2 p-3">
                            <Button
                                size="icon-xs"
                                className="absolute top-1.5 right-1.5"
                                aria-label={atRoot ? 'Cancel new collection' : 'Cancel new folder'}
                                tooltip={atRoot ? 'Cancel new collection' : 'Cancel new folder'}
                                onClick={() => setNewFolderOpen(false)}
                                data-attr="analytics-share-new-folder-cancel"
                            >
                                <IconX />
                            </Button>
                            <form
                                className="flex items-end gap-2"
                                onSubmit={(event) => {
                                    event.preventDefault()
                                    if (newFolderName.trim() && !creatingFolder) {
                                        createFolder()
                                    }
                                }}
                            >
                                <Field className="flex-1">
                                    <FieldLabel htmlFor="analytics-share-new-folder-name">
                                        {atRoot ? 'Collection name' : 'Folder name'}
                                    </FieldLabel>
                                    <Input
                                        id="analytics-share-new-folder-name"
                                        autoFocus
                                        placeholder={atRoot ? 'Growth team' : 'Q4 launch'}
                                        value={newFolderName}
                                        onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
                                            setNewFolderName(event.target.value)
                                        }
                                        onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                                            if (event.key === 'Escape') {
                                                event.preventDefault()
                                                event.stopPropagation()
                                                setNewFolderOpen(false)
                                            }
                                        }}
                                        data-attr="analytics-share-new-folder-name"
                                    />
                                </Field>
                                <Button
                                    type="submit"
                                    variant="outline"
                                    loading={creatingFolder}
                                    disabledReason={newFolderName.trim() ? undefined : 'Enter a name'}
                                    data-attr="analytics-share-new-folder-create"
                                >
                                    Create
                                </Button>
                            </form>
                        </Card>
                    )}
                    {loading ? (
                        <div className="flex flex-col gap-2" aria-busy>
                            <Skeleton className="h-11" />
                            <Skeleton className="h-11" />
                            <Skeleton className="h-11" />
                        </div>
                    ) : failed ? (
                        <Empty className="py-8">
                            <EmptyHeader>
                                <EmptyTitle>Couldn’t load this folder. Close this and try again.</EmptyTitle>
                            </EmptyHeader>
                        </Empty>
                    ) : !rows.length ? (
                        <Empty className="py-8">
                            <EmptyHeader>
                                <EmptyMedia variant="icon">
                                    <IconFolder />
                                </EmptyMedia>
                                <EmptyTitle>{emptyMessage}</EmptyTitle>
                            </EmptyHeader>
                        </Empty>
                    ) : (
                        <CardGroup size="sm">
                            {rows.map((row) => {
                                const isFolder = row.kind === 'folder'
                                const media =
                                    row.kind !== 'folder' ? (
                                        <span className="flex size-6 shrink-0 items-center justify-center text-base text-muted-foreground">
                                            <AnalyticsTypeIcon type={row.kind} />
                                        </span>
                                    ) : splitPath(row.path).length === 1 ? (
                                        <AnalyticsSpaceGlyph name={row.name} size="md" />
                                    ) : (
                                        <IconFolder className="size-6 shrink-0 text-muted-foreground" />
                                    )
                                const description = row.path === currentFolder ? 'Current location' : row.description
                                const label = (
                                    <span className="flex min-w-0 flex-1 flex-col leading-tight">
                                        <Text
                                            size="sm"
                                            variant={isFolder ? undefined : 'muted'}
                                            className="m-0 truncate"
                                            render={<span />}
                                        >
                                            {row.name}
                                        </Text>
                                        {description && (
                                            <Text size="xs" variant="muted" className="m-0 truncate" render={<span />}>
                                                {description}
                                            </Text>
                                        )}
                                    </span>
                                )
                                return (
                                    <Card key={row.path} size="sm" className="p-0">
                                        {isFolder ? (
                                            <button
                                                type="button"
                                                className={OPENABLE_ROW_CLASS}
                                                onClick={() => browseTo(row.path)}
                                                data-attr="analytics-share-open-folder"
                                            >
                                                {media}
                                                {label}
                                                <IconChevronRight
                                                    className="size-4 shrink-0 text-muted-foreground"
                                                    aria-hidden
                                                />
                                            </button>
                                        ) : (
                                            <div className={ROW_CLASS}>
                                                {media}
                                                {label}
                                            </div>
                                        )}
                                    </Card>
                                )
                            })}
                        </CardGroup>
                    )}
                </DialogBody>
                <DialogFooter className="sm:justify-between">
                    <Button
                        variant="outline"
                        disabledReason={
                            newFolderOpen ? 'Name the new one first' : searching ? 'Clear the search first' : undefined
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
                            <span className="truncate">
                                {destinationName && !searching
                                    ? `${moving ? 'Move' : 'Add'} to ${destinationName}`
                                    : moving
                                      ? 'Move'
                                      : 'Add'}
                            </span>
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
