import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconChevronDown, IconGear } from '@posthog/icons'
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
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    collapseButton: ReactNode
}): JSX.Element {
    const { selectedRecordingsIds, otherRecordings, listSort } = useValues(sessionRecordingsPlaylistLogic)
    const { handleSelectUnselectAll } = useActions(sessionRecordingsPlaylistLogic)
    const viewItems = useWatchViewMenuItems(filters, setFilters)
    const settingsItems = useWatchSettingsMenuItems()

    const allSelected = otherRecordings.length > 0 && selectedRecordingsIds.length === otherRecordings.length
    const selectAllDisabledReason =
        otherRecordings.length === 0
            ? 'No recordings'
            : otherRecordings.length > MAX_SELECTED_RECORDINGS
              ? `Cannot select more than ${MAX_SELECTED_RECORDINGS} recordings at once`
              : undefined

    return (
        <div
            className="shrink-0 bg-bg-3000 flex items-center gap-0.5 whitespace-nowrap border-b text-xs"
            data-attr="list-header-bar"
        >
            <Tooltip title={selectAllDisabledReason ? undefined : 'Select all recordings'}>
                <span className="flex ml-[7px] mr-1">
                    <LemonCheckbox
                        disabledReason={selectAllDisabledReason}
                        checked={allSelected}
                        onChange={(checked) => handleSelectUnselectAll(checked, 'filters')}
                        stopPropagation
                        data-attr="select-all-recordings"
                        aria-label="Select all recordings"
                    />
                </span>
            </Tooltip>
            {selectedRecordingsIds.length > 0 ? (
                <ReplayBulkBar type="filters" />
            ) : (
                <div className="ml-auto flex items-center gap-0.5">
                    <LemonMenu items={viewItems} placement="bottom-end" buttonSize="xsmall" closeOnClickInside={false}>
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
            )}
        </div>
    )
}
