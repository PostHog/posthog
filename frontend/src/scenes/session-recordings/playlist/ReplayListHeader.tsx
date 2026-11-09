import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheckbox, IconChevronDown, IconGear, IconSidebarClose } from '@posthog/icons'
import {
    Button,
    Checkbox,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
    Separator,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { RecordingUniversalFilters } from '~/types'

import { QuillMenuItems } from './QuillMenuItems'
import { ReplayBulkBar } from './ReplayBulkBar'
import { MAX_SELECTED_RECORDINGS, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { useWatchSettingsMenuItems, useWatchViewMenuItems, watchSortLabel } from './watchListViewMenuItems'

export function ReplayListHeader({
    filters,
    setFilters,
    onCollapse,
    type = 'filters',
    shortId,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    onCollapse: () => void
    type?: 'filters' | 'collection'
    shortId?: string
}): JSX.Element {
    const { selectedRecordingsIds, otherRecordings, visiblePinnedRecordings, listSort, selectMode } =
        useValues(sessionRecordingsPlaylistLogic)
    const { setSelectedRecordingsIds, setSelectMode } = useActions(sessionRecordingsPlaylistLogic)
    const viewItems = useWatchViewMenuItems(filters, setFilters)
    const settingsItems = useWatchSettingsMenuItems()

    useEffect(() => {
        if (!selectMode) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            // An open dialog or menu owns Escape.
            if (event.key === 'Escape' && !document.querySelector('.LemonModal, .Popover, [data-quill-portal]')) {
                setSelectMode(false)
            }
        }
        document.addEventListener('keydown', onKeyDown)
        return () => document.removeEventListener('keydown', onKeyDown)
    }, [selectMode, setSelectMode])

    const recordings = type === 'filters' ? otherRecordings.filter((r) => !r.ongoing) : visiblePinnedRecordings
    const hasOngoing = type === 'filters' && recordings.length < otherRecordings.length
    const allSelected = recordings.length > 0 && recordings.every((r) => selectedRecordingsIds.includes(r.id))
    const selectAllDisabledReason =
        recordings.length === 0
            ? 'No recordings'
            : recordings.length > MAX_SELECTED_RECORDINGS
              ? `Cannot select more than ${MAX_SELECTED_RECORDINGS} recordings at once`
              : undefined

    return (
        <div
            data-quill
            className="@container/list-header shrink-0 min-w-0 bg-muted text-foreground flex items-center gap-0.5 whitespace-nowrap border-b border-border text-xs"
            data-attr="list-header-bar"
        >
            {selectMode ? (
                <>
                    <Tooltip disabled={!!selectAllDisabledReason}>
                        <TooltipTrigger render={<span className="flex ml-[7px] mr-1" />}>
                            <Checkbox
                                disabledReason={selectAllDisabledReason}
                                checked={allSelected}
                                onCheckedChange={(checked) =>
                                    setSelectedRecordingsIds(checked ? recordings.map((r) => r.id) : [])
                                }
                                data-attr="select-all-recordings"
                                aria-label="Select all recordings"
                            />
                        </TooltipTrigger>
                        <TooltipContent>
                            {hasOngoing ? 'Select all finished recordings' : 'Select all recordings'}
                        </TooltipContent>
                    </Tooltip>
                    {selectedRecordingsIds.length > 0 ? (
                        <ReplayBulkBar type={type} shortId={shortId} />
                    ) : (
                        <span className="text-muted-foreground px-1">Select recordings</span>
                    )}
                    <Button
                        variant="outline"
                        size="sm"
                        className="ml-auto mr-1"
                        onClick={() => setSelectMode(false)}
                        tooltip="Done selecting (Esc)"
                        data-attr="list-select-done"
                    >
                        Done
                    </Button>
                </>
            ) : (
                <>
                    <Button
                        size="sm"
                        className="ml-1"
                        onClick={() => setSelectMode(true)}
                        disabledReason={recordings.length === 0 ? 'No recordings' : undefined}
                        data-attr="list-select-mode"
                    >
                        <IconCheckbox />
                        Select
                    </Button>
                    <div className="ml-auto flex items-center gap-0.5">
                        <DropdownMenu>
                            <DropdownMenuTrigger render={<Button size="sm" data-attr="list-view-menu" />}>
                                {watchSortLabel(listSort.order ?? filters.order)}
                                <IconChevronDown />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                                <QuillMenuItems items={viewItems} closeOnClick={false} />
                            </DropdownMenuContent>
                        </DropdownMenu>
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={
                                    <Button
                                        size="icon-sm"
                                        tooltip="List settings"
                                        aria-label="List settings"
                                        data-attr="list-settings-menu"
                                    />
                                }
                            >
                                <IconGear />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                                <QuillMenuItems items={settingsItems} closeOnClick={false} />
                            </DropdownMenuContent>
                        </DropdownMenu>
                        <Separator orientation="vertical" className="h-4 mx-0.5" />
                        <Button
                            size="icon-sm"
                            onClick={onCollapse}
                            tooltip="Collapse playlist"
                            aria-label="Collapse playlist"
                            data-attr="collapse-playlist"
                        >
                            <IconSidebarClose className="rotate-180" />
                        </Button>
                    </div>
                </>
            )}
        </div>
    )
}
