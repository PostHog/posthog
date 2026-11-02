import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconChevronDown, IconFilter } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'

import { SessionRecordingPlaylistType } from '~/types'

import { playlistFiltersLogic } from './playlistFiltersLogic'
import { stripSessionIds } from './playlistUtils'
import { QuillMenuItems } from './QuillMenuItems'
import { asUniversalFilters, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

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

    const apply = (filter: SessionRecordingPlaylistType): void => {
        const universal = asUniversalFilters(filter.filters)
        if (!universal) {
            return
        }
        applySavedFilter(stripSessionIds(universal))
        setAppliedSavedFilter(filter)
    }

    const items: LemonMenuItems = [
        {
            items: [
                {
                    label: 'All recordings',
                    active: !appliedSavedFilter,
                    onClick: () => {
                        resetFilters()
                        setAppliedSavedFilter(null)
                    },
                    'data-attr': 'list-saved-filter-reset',
                },
            ],
        },
        ...(savedFilters.results.length > 0
            ? [
                  {
                      title: 'Saved filters',
                      items: savedFilters.results.map((filter) => ({
                          label: savedFilterName(filter),
                          active: filter.short_id === appliedSavedFilter?.short_id,
                          onClick: () => apply(filter),
                          'data-attr': 'list-saved-filter-apply',
                      })),
                  },
              ]
            : []),
        {
            items: [
                { label: 'Save current filters', onClick: onSaveCurrent, 'data-attr': 'list-saved-filter-save' },
                {
                    label: 'Manage saved filters',
                    onClick: () => {
                        setActiveFilterTab('saved')
                        setIsFiltersExpanded(true)
                    },
                    'data-attr': 'list-saved-filter-manage',
                },
            ],
        },
    ]

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant={appliedSavedFilter ? 'secondary' : 'outline'}
                        className="max-w-60"
                        data-attr="list-saved-filter-select"
                    />
                }
            >
                {appliedSavedFilter && <IconFilter />}
                <span className="truncate">
                    {appliedSavedFilter
                        ? `${savedFilterName(appliedSavedFilter)}${edited ? ' (edited)' : ''}`
                        : 'All recordings'}
                </span>
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                <QuillMenuItems items={items} />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
