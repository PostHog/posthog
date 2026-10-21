import { deepEqual as equal } from 'fast-equals'
import { useActions, useValues } from 'kea'
import { ReactNode, useState } from 'react'

import { IconChevronDown, IconFilter, IconGear, IconRefresh } from '@posthog/icons'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { MaxTool } from 'scenes/max/MaxTool'
import { SaveFiltersModal } from 'scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed'
import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'
import { useRecordingFiltersAssist } from 'scenes/session-recordings/filters/useRecordingFiltersAssist'

import { RecordingUniversalFilters } from '~/types'

import { FilterChips } from './FilterChips'
import { playlistFiltersLogic } from './playlistFiltersLogic'
import { ReplayBulkBar } from './ReplayBulkBar'
import { SavedFilterEditedBar } from './SavedFilterEditedBar'
import { SavedFilterSelect } from './SavedFilterSelect'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { useWatchSettingsMenuItems, useWatchViewMenuItems, watchSortLabel } from './watchListViewMenuItems'

/** The watch layout's list header: saved filter, add filter, chips, sort, settings; the bulk bar while selecting. */
export function ReplayFilterBar({
    filters,
    setFilters,
    totalFiltersCount,
    currentSessionRecordingId,
    onReload,
    collapseButton,
    type,
    shortId,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    totalFiltersCount?: number
    currentSessionRecordingId?: string
    onReload: () => void
    collapseButton: ReactNode
    type: 'filters' | 'collection'
    shortId?: string
}): JSX.Element {
    const { selectedRecordingsIds, sessionRecordingsResponseLoading, listSort } =
        useValues(sessionRecordingsPlaylistLogic)
    const { isFiltersExpanded } = useValues(playlistFiltersLogic)
    const { setIsFiltersExpanded } = useActions(playlistFiltersLogic)
    const { appliedSavedFilter } = useValues(sessionRecordingSavedFiltersLogic)
    const { applyFilters } = useRecordingFiltersAssist({ filters, setFilters, currentSessionRecordingId })
    const viewItems = useWatchViewMenuItems(filters, setFilters)
    const settingsItems = useWatchSettingsMenuItems()
    const [saveModalOpen, setSaveModalOpen] = useState(false)

    const edited = !!appliedSavedFilter && !equal(appliedSavedFilter.filters, filters)

    if (selectedRecordingsIds.length > 0) {
        return <ReplayBulkBar type={type} shortId={shortId} />
    }

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1 flex-wrap" data-attr="list-filter-bar">
                <SavedFilterSelect
                    setFilters={setFilters}
                    edited={edited}
                    onSaveCurrent={() => setSaveModalOpen(true)}
                />
                <MaxTool
                    identifier="filter_session_recordings"
                    context={{ current_filters: filters, current_session_id: currentSessionRecordingId }}
                    callback={applyFilters}
                    initialMaxPrompt="Show me recordings where "
                    suggestions={[
                        'Show recordings of people who visited signup in the last 24 hours',
                        'Show recordings showing user frustration',
                        'Show recordings of people who faced bugs',
                    ]}
                    onMaxOpen={() => setIsFiltersExpanded(false)}
                >
                    <LemonButton
                        size="small"
                        type="secondary"
                        active={isFiltersExpanded}
                        icon={<IconFilter />}
                        onClick={() => setIsFiltersExpanded(!isFiltersExpanded)}
                        tooltip={isFiltersExpanded ? 'Hide filters' : 'Add a filter'}
                        aria-label="Add a filter"
                        data-attr="filter-recordings-button"
                    >
                        {totalFiltersCount ? <LemonBadge.Number count={totalFiltersCount} size="small" /> : null}
                    </LemonButton>
                </MaxTool>
                <FilterChips filters={filters} setFilters={setFilters} />
                <div className="ml-auto flex items-center gap-0.5">
                    <LemonMenu items={viewItems} placement="bottom-end" buttonSize="small" closeOnClickInside={false}>
                        <LemonButton size="small" sideIcon={<IconChevronDown />} data-attr="list-view-menu">
                            {watchSortLabel(listSort.order ?? filters.order)}
                        </LemonButton>
                    </LemonMenu>
                    <LemonMenu
                        items={settingsItems}
                        placement="bottom-end"
                        buttonSize="small"
                        closeOnClickInside={false}
                    >
                        <LemonButton
                            size="small"
                            icon={<IconGear />}
                            tooltip="List settings"
                            aria-label="List settings"
                            data-attr="list-settings-menu"
                        />
                    </LemonMenu>
                    <LemonButton
                        size="small"
                        icon={<IconRefresh />}
                        loading={sessionRecordingsResponseLoading}
                        onClick={onReload}
                        tooltip="Refresh list"
                        aria-label="Refresh list"
                        data-attr="refresh-recordings-list"
                    />
                    {collapseButton}
                </div>
            </div>
            {edited && (
                <SavedFilterEditedBar
                    filters={filters}
                    setFilters={setFilters}
                    onSaveAsCopy={() => setSaveModalOpen(true)}
                />
            )}
            <SaveFiltersModal isOpen={saveModalOpen} setIsOpen={setSaveModalOpen} filters={filters} />
        </div>
    )
}
