import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconChevronDown, IconFilter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'

import { RecordingUniversalFilters, SessionRecordingPlaylistType } from '~/types'

import { playlistFiltersLogic } from './playlistFiltersLogic'
import { stripSessionIds } from './playlistUtils'
import { asUniversalFilters, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

const savedFilterName = (filter: SessionRecordingPlaylistType): string =>
    filter.name || filter.derived_name || 'Unnamed'

export function SavedFilterSelect({
    setFilters,
    edited,
    onSaveCurrent,
}: {
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    edited: boolean
    onSaveCurrent: () => void
}): JSX.Element {
    const { savedFilters, appliedSavedFilter } = useValues(sessionRecordingSavedFiltersLogic)
    const { setAppliedSavedFilter, loadSavedFiltersIfNeeded } = useActions(sessionRecordingSavedFiltersLogic)
    const { resetFilters } = useActions(sessionRecordingsPlaylistLogic)
    const { setIsFiltersExpanded, setActiveFilterTab } = useActions(playlistFiltersLogic)

    useEffect(() => {
        loadSavedFiltersIfNeeded()
    }, [loadSavedFiltersIfNeeded])

    const apply = (filter: SessionRecordingPlaylistType): void => {
        const universal = asUniversalFilters(filter.filters)
        if (!universal) {
            return
        }
        setFilters(stripSessionIds(universal))
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
        <LemonMenu items={items} placement="bottom-start" buttonSize="small">
            <LemonButton
                size="small"
                type="secondary"
                active={!!appliedSavedFilter}
                icon={appliedSavedFilter ? <IconFilter /> : undefined}
                sideIcon={<IconChevronDown />}
                className="max-w-60"
                truncate
                data-attr="list-saved-filter-select"
            >
                {appliedSavedFilter
                    ? `${savedFilterName(appliedSavedFilter)}${edited ? ' (edited)' : ''}`
                    : 'All recordings'}
            </LemonButton>
        </LemonMenu>
    )
}
