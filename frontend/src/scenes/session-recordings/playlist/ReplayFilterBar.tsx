import { deepEqual as equal } from 'fast-equals'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconFilter, IconRefresh } from '@posthog/icons'
import { Badge, Button, Toggle, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { useMaxTool } from 'scenes/max/useMaxTool'
import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'
import { useRecordingFiltersAssist } from 'scenes/session-recordings/filters/useRecordingFiltersAssist'

import { RecordingUniversalFilters } from '~/types'

import { FilterChips } from './FilterChips'
import { playlistFiltersLogic } from './playlistFiltersLogic'
import { comparableRecordingFilters } from './playlistUtils'
import { QuillSaveFiltersModal } from './QuillSaveFiltersModal'
import { SavedFilterEditedBar } from './SavedFilterEditedBar'
import { SavedFilterSelect } from './SavedFilterSelect'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

function withoutSort(filters: RecordingUniversalFilters): Partial<RecordingUniversalFilters> {
    const { order: _order, order_direction: _direction, ...rest } = filters
    return comparableRecordingFilters(rest)
}

export function ReplayFilterBar({
    filters,
    setFilters,
    totalFiltersCount,
    currentSessionRecordingId,
    onReload,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    totalFiltersCount?: number
    currentSessionRecordingId?: string
    onReload: () => void
}): JSX.Element {
    const { sessionRecordingsResponseLoading, defaultFilters } = useValues(sessionRecordingsPlaylistLogic)
    const { isFiltersExpanded } = useValues(playlistFiltersLogic)
    const { setIsFiltersExpanded } = useActions(playlistFiltersLogic)
    const { appliedSavedFilter, appliedSavedFilterFilters } = useValues(sessionRecordingSavedFiltersLogic)
    const { setAppliedSavedFilter } = useActions(sessionRecordingSavedFiltersLogic)
    const { applyFilters } = useRecordingFiltersAssist({ filters, setFilters, currentSessionRecordingId })
    useMaxTool({
        identifier: 'filter_session_recordings',
        context: { current_filters: filters, current_session_id: currentSessionRecordingId },
        callback: applyFilters,
        initialMaxPrompt: 'Show me recordings where ',
        suggestions: [
            'Show recordings of people who visited signup in the last 24 hours',
            'Show recordings showing user frustration',
            'Show recordings of people who faced bugs',
        ],
        onMaxOpen: () => setIsFiltersExpanded(false),
    })
    const [saveModalOpen, setSaveModalOpen] = useState(false)

    const edited = !!appliedSavedFilter && !equal(appliedSavedFilterFilters, comparableRecordingFilters(filters))
    const filtersAreDefault = equal(withoutSort(filters), withoutSort(defaultFilters))
    useEffect(() => {
        if (appliedSavedFilter && filtersAreDefault) {
            setAppliedSavedFilter(null)
        }
    }, [appliedSavedFilter, filtersAreDefault, setAppliedSavedFilter])

    return (
        <div data-quill className="flex flex-col gap-1 text-foreground">
            <div className="flex items-start gap-1" data-attr="list-filter-bar">
                <div className="flex flex-1 min-w-0 items-center gap-1 flex-wrap">
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Toggle
                                    variant="outline"
                                    pressed={isFiltersExpanded}
                                    onPressedChange={setIsFiltersExpanded}
                                    aria-label="Add a filter"
                                    data-attr="filter-recordings-button"
                                />
                            }
                        >
                            <IconFilter />
                            {totalFiltersCount ? <Badge>{totalFiltersCount}</Badge> : null}
                        </TooltipTrigger>
                        <TooltipContent>{isFiltersExpanded ? 'Hide filters' : 'Add a filter'}</TooltipContent>
                    </Tooltip>
                    <SavedFilterSelect edited={edited} onSaveCurrent={() => setSaveModalOpen(true)} />
                    <FilterChips filters={filters} setFilters={setFilters} />
                </div>
                <Button
                    variant="outline"
                    size="icon"
                    className="shrink-0"
                    loading={sessionRecordingsResponseLoading}
                    onClick={onReload}
                    tooltip="Refresh list"
                    aria-label="Refresh list"
                    data-attr="refresh-recordings-list"
                >
                    <IconRefresh />
                </Button>
            </div>
            {edited && <SavedFilterEditedBar filters={filters} onSaveAsCopy={() => setSaveModalOpen(true)} />}
            <QuillSaveFiltersModal isOpen={saveModalOpen} setIsOpen={setSaveModalOpen} filters={filters} />
        </div>
    )
}
