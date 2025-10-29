import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isActionFilter, isEventFilter, isLogEntryPropertyFilter } from 'lib/components/UniversalFilters/utils'

import { cohortsModel } from '~/models/cohortsModel'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { summarizePlaylistFilters } from '../playlist/playlistUtils'
import { sessionRecordingsPlaylistLogic } from '../playlist/sessionRecordingsPlaylistLogic'
import { filtersFromUniversalFilterGroups } from '../utils'
import { sessionRecordingSavedFiltersLogic } from './sessionRecordingSavedFiltersLogic'

function formatDateRange(dateFrom: string | null, dateTo: string | null): string {
    if (!dateFrom && !dateTo) {
        return 'All time'
    }
    if (dateFrom?.startsWith('-')) {
        const days = dateFrom.replace('-', '').replace('d', '')
        return `Last ${days} day${days === '1' ? '' : 's'}`
    }
    return dateFrom || dateTo || 'All time'
}

function formatDuration(filter: any): string | null {
    if (!filter) {
        return null
    }
    const { value, operator } = filter
    if (operator === PropertyOperator.GreaterThan) {
        return `Longer than ${value} second${value === 1 ? '' : 's'}`
    }
    if (operator === PropertyOperator.LessThan) {
        return `Shorter than ${value} second${value === 1 ? '' : 's'}`
    }
    return null
}

function formatPropertyFilter(filter: AnyPropertyFilter): string | null {
    const taxonomicType =
        filter.type === PropertyFilterType.Session
            ? TaxonomicFilterGroupType.SessionProperties
            : filter.type === PropertyFilterType.Event
              ? TaxonomicFilterGroupType.EventProperties
              : filter.type === PropertyFilterType.Person
                ? TaxonomicFilterGroupType.PersonProperties
                : filter.type === PropertyFilterType.Recording
                  ? TaxonomicFilterGroupType.Replay
                  : null

    const label = taxonomicType ? (getCoreFilterDefinition(filter.key, taxonomicType)?.label ?? filter.key) : filter.key
    const value = Array.isArray(filter.value) ? filter.value.join(', ') : filter.value

    return `${label} = ${value}`
}

export function CurrentFilterIndicator(): JSX.Element | null {
    const { appliedSavedFilter } = useValues(sessionRecordingSavedFiltersLogic)
    const { setAppliedSavedFilter } = useActions(sessionRecordingSavedFiltersLogic)
    const { resetFilters } = useActions(sessionRecordingsPlaylistLogic)
    const { filters: filtersValues } = useValues(sessionRecordingsPlaylistLogic)
    const { cohortsById } = useValues(cohortsModel)

    const handleClearFilter = (): void => {
        resetFilters()
        setAppliedSavedFilter(null)
    }

    // Build filter description
    const filterParts: string[] = []

    // Date range - always show
    filterParts.push(formatDateRange(filtersValues.date_from, filtersValues.date_to))

    // Duration - always show if present
    const durationFilter = filtersValues.duration?.[0]
    if (durationFilter) {
        const formatted = formatDuration(durationFilter)
        if (formatted) {
            filterParts.push(formatted)
        }
    }

    // Property/event/action filters
    const groupFilters = filtersFromUniversalFilterGroups(filtersValues)

    // Handle console log filters
    const consoleLogFilters = groupFilters.filter(isLogEntryPropertyFilter)
    consoleLogFilters.forEach((filter) => {
        if (filter.key === 'level' && Array.isArray(filter.value)) {
            filterParts.push(`Console log level = ${filter.value.join(', ')}`)
        } else if (filter.key === 'message') {
            filterParts.push(`Console log message: ${filter.value}`)
        }
    })

    // Handle property filters (session, event, person, recording)
    const propertyFilters = groupFilters.filter(
        (f) => !isLogEntryPropertyFilter(f) && !isEventFilter(f) && !isActionFilter(f) && isValidPropertyFilter(f)
    )
    propertyFilters.forEach((filter) => {
        const formatted = formatPropertyFilter(filter as AnyPropertyFilter)
        if (formatted) {
            filterParts.push(formatted)
        }
    })

    // Handle event/action filters
    const eventActionFilters = groupFilters.filter((f) => isEventFilter(f) || isActionFilter(f))
    const filterSummary = summarizePlaylistFilters(eventActionFilters, cohortsById)
    if (filterSummary) {
        filterParts.push(filterSummary)
    }

    // If we have a saved filter, only show the filter name
    if (appliedSavedFilter) {
        return (
            <div className="border rounded p-2 mx-2 my-2">
                <div className="text-xs text-muted flex items-center justify-between gap-1">
                    <div className="flex-1 min-w-0">
                        <div className="font-semibold">Current filter applied:</div>
                        <div
                            className="truncate"
                            title={appliedSavedFilter.name || appliedSavedFilter.derived_name || 'Unnamed'}
                        >
                            {appliedSavedFilter.name || appliedSavedFilter.derived_name || 'Unnamed'}
                        </div>
                    </div>
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        onClick={handleClearFilter}
                        tooltip="Clear filter and reset to default"
                        noPadding
                    />
                </div>
            </div>
        )
    }

    return (
        <div className="border rounded p-2 mx-2 my-2">
            <div className="text-xs text-muted flex items-center justify-between gap-1">
                <div className="flex-1 min-w-0">
                    <div className="font-semibold">Active filters:</div>
                    <div className="truncate" title={filterParts.join(', ')}>
                        {filterParts.join(', ')}
                    </div>
                </div>
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    onClick={handleClearFilter}
                    tooltip="Clear filter and reset to default"
                    noPadding
                />
            </div>
        </div>
    )
}
