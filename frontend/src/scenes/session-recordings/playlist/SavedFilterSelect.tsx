import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconFilter } from '@posthog/icons'
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectSeparator,
    SelectTrigger,
} from '@posthog/quill'

import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'

import { SessionRecordingPlaylistType } from '~/types'

import { playlistFiltersLogic } from './playlistFiltersLogic'
import { stripSessionIds } from './playlistUtils'
import { asUniversalFilters, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

const ALL_RECORDINGS = 'all'
const SAVE_CURRENT = 'save'
const MANAGE = 'manage'

const savedFilterName = (filter: SessionRecordingPlaylistType): string =>
    filter.name || filter.derived_name || 'Unnamed'

export function SavedFilterSelect({
    edited,
    onSaveCurrent,
}: {
    edited: boolean
    onSaveCurrent: () => void
}): JSX.Element {
    const { savedFilters, appliedSavedFilter } = useValues(sessionRecordingSavedFiltersLogic)
    const { setAppliedSavedFilter, loadSavedFiltersIfNeeded } = useActions(sessionRecordingSavedFiltersLogic)
    const { resetFilters, applySavedFilter } = useActions(sessionRecordingsPlaylistLogic)
    const { setIsFiltersExpanded, setActiveFilterTab } = useActions(playlistFiltersLogic)

    useEffect(() => {
        loadSavedFiltersIfNeeded()
    }, [loadSavedFiltersIfNeeded])

    const onValueChange = (value: string | null): void => {
        if (value === SAVE_CURRENT) {
            onSaveCurrent()
            return
        }
        if (value === MANAGE) {
            setActiveFilterTab('saved')
            setIsFiltersExpanded(true)
            return
        }
        if (value === null || value === ALL_RECORDINGS) {
            resetFilters()
            setAppliedSavedFilter(null)
            return
        }
        const filter = savedFilters.results.find((candidate) => candidate.short_id === value)
        const universal = filter && asUniversalFilters(filter.filters)
        if (!filter || !universal) {
            return
        }
        applySavedFilter(stripSessionIds(universal))
        setAppliedSavedFilter(filter)
    }

    return (
        <Select value={appliedSavedFilter?.short_id ?? ALL_RECORDINGS} onValueChange={onValueChange}>
            <SelectTrigger className="max-w-60" data-attr="list-saved-filter-select">
                {appliedSavedFilter && <IconFilter />}
                <span className="truncate">
                    {appliedSavedFilter
                        ? `${savedFilterName(appliedSavedFilter)}${edited ? ' (edited)' : ''}`
                        : 'All recordings'}
                </span>
            </SelectTrigger>
            <SelectContent>
                <SelectItem value={ALL_RECORDINGS} data-attr="list-saved-filter-reset">
                    All recordings
                </SelectItem>
                {savedFilters.results.length > 0 && (
                    <>
                        <SelectSeparator />
                        <SelectGroup>
                            <SelectGroupLabel>Saved filters</SelectGroupLabel>
                            {savedFilters.results.map((filter) => (
                                <SelectItem
                                    key={filter.short_id}
                                    value={filter.short_id}
                                    data-attr="list-saved-filter-apply"
                                >
                                    {savedFilterName(filter)}
                                </SelectItem>
                            ))}
                        </SelectGroup>
                    </>
                )}
                <SelectSeparator />
                <SelectItem value={SAVE_CURRENT} data-attr="list-saved-filter-save">
                    Save current filters
                </SelectItem>
                <SelectItem value={MANAGE} data-attr="list-saved-filter-manage">
                    Manage saved filters
                </SelectItem>
            </SelectContent>
        </Select>
    )
}
