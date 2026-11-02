import { deepEqual as equal } from 'fast-equals'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter, IconRefresh } from '@posthog/icons'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'

import { useMaxTool } from 'scenes/max/useMaxTool'
import { SaveFiltersModal } from 'scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed'
import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'
import { useRecordingFiltersAssist } from 'scenes/session-recordings/filters/useRecordingFiltersAssist'

import { RecordingUniversalFilters } from '~/types'

import { FilterChips } from './FilterChips'
import { playlistFiltersLogic } from './playlistFiltersLogic'
import { comparableRecordingFilters } from './playlistUtils'
import { SavedFilterChips } from './SavedFilterChips'
import { SavedFilterEditedBar } from './SavedFilterEditedBar'
import { SavedFilterSelect } from './SavedFilterSelect'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function ReplayFilterBar({
    filters,
    setFilters,
    totalFiltersCount,
    currentSessionRecordingId,
    onReload,
    savedFilterChips,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    totalFiltersCount?: number
    currentSessionRecordingId?: string
    onReload: () => void
    savedFilterChips?: boolean
}): JSX.Element {
    const { sessionRecordingsResponseLoading } = useValues(sessionRecordingsPlaylistLogic)
    const { isFiltersExpanded } = useValues(playlistFiltersLogic)
    const { setIsFiltersExpanded } = useActions(playlistFiltersLogic)
    const { appliedSavedFilter, appliedSavedFilterFilters } = useValues(sessionRecordingSavedFiltersLogic)
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

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-start gap-1" data-attr="list-filter-bar">
                <div className="flex flex-1 min-w-0 items-center gap-1 flex-wrap">
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
                    <SavedFilterSelect edited={edited} onSaveCurrent={() => setSaveModalOpen(true)} />
                    {savedFilterChips && <SavedFilterChips edited={edited} />}
                    <FilterChips filters={filters} setFilters={setFilters} />
                </div>
                <LemonButton
                    size="small"
                    type="secondary"
                    className="shrink-0"
                    icon={<IconRefresh />}
                    loading={sessionRecordingsResponseLoading}
                    onClick={onReload}
                    tooltip="Refresh list"
                    aria-label="Refresh list"
                    data-attr="refresh-recordings-list"
                />
            </div>
            {edited && <SavedFilterEditedBar filters={filters} onSaveAsCopy={() => setSaveModalOpen(true)} />}
            <SaveFiltersModal isOpen={saveModalOpen} setIsOpen={setSaveModalOpen} filters={filters} />
        </div>
    )
}
