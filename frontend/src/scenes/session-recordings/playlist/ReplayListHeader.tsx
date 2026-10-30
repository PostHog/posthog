import { useActions, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'

import { IconCheckbox, IconChevronDown, IconGear } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDivider } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { RecordingUniversalFilters } from '~/types'

import { ReplayBulkBar } from './ReplayBulkBar'
import { MAX_SELECTED_RECORDINGS, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { useWatchSettingsMenuItems, useWatchViewMenuItems, watchSortLabel } from './watchListViewMenuItems'

export function ReplayListHeader({
    filters,
    setFilters,
    collapseButton,
    type = 'filters',
    shortId,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    collapseButton: ReactNode
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
            if (event.key === 'Escape' && !document.querySelector('.LemonModal, .Popover')) {
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
            className="@container/list-header shrink-0 min-w-0 bg-bg-3000 flex items-center gap-0.5 whitespace-nowrap border-b text-xs"
            data-attr="list-header-bar"
        >
            {selectMode ? (
                <>
                    <Tooltip
                        title={
                            selectAllDisabledReason
                                ? undefined
                                : hasOngoing
                                  ? 'Select all finished recordings'
                                  : 'Select all recordings'
                        }
                    >
                        <span className="flex ml-[7px] mr-1">
                            <LemonCheckbox
                                disabledReason={selectAllDisabledReason}
                                checked={allSelected}
                                onChange={(checked) =>
                                    setSelectedRecordingsIds(checked ? recordings.map((r) => r.id) : [])
                                }
                                stopPropagation
                                data-attr="select-all-recordings"
                                aria-label="Select all recordings"
                            />
                        </span>
                    </Tooltip>
                    {selectedRecordingsIds.length > 0 ? (
                        <ReplayBulkBar type={type} shortId={shortId} />
                    ) : (
                        <span className="text-secondary px-1">Select recordings</span>
                    )}
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        className="ml-auto mr-1"
                        onClick={() => setSelectMode(false)}
                        tooltip="Done selecting (Esc)"
                        data-attr="list-select-done"
                    >
                        Done
                    </LemonButton>
                </>
            ) : (
                <>
                    <LemonButton
                        size="xsmall"
                        icon={<IconCheckbox />}
                        className="ml-1"
                        onClick={() => setSelectMode(true)}
                        disabledReason={recordings.length === 0 ? 'No recordings' : undefined}
                        data-attr="list-select-mode"
                    >
                        Select
                    </LemonButton>
                    <div className="ml-auto flex items-center gap-0.5">
                        <LemonMenu
                            items={viewItems}
                            placement="bottom-end"
                            buttonSize="xsmall"
                            closeOnClickInside={false}
                        >
                            <LemonButton size="xsmall" sideIcon={<IconChevronDown />} data-attr="list-view-menu">
                                {watchSortLabel(listSort.order ?? filters.order)}
                            </LemonButton>
                        </LemonMenu>
                        <LemonMenu
                            items={settingsItems}
                            placement="bottom-end"
                            buttonSize="xsmall"
                            closeOnClickInside={false}
                        >
                            <LemonButton
                                size="xsmall"
                                icon={<IconGear />}
                                tooltip="List settings"
                                aria-label="List settings"
                                data-attr="list-settings-menu"
                            />
                        </LemonMenu>
                        <LemonDivider vertical className="my-1 mx-0.5" />
                        {collapseButton}
                    </div>
                </>
            )}
        </div>
    )
}
