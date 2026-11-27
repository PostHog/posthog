import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuSeparator,
    FilterClearItem,
    FilterOption,
    FilterMenuTrigger,
    FilterRadioSubMenu,
} from '@posthog/quill'

import { SEVERITIES } from './ingestionWarningSeverity'
import { IngestionWarningsTimeWindow, ingestionWarningsV2Logic } from './ingestionWarningsV2Logic'

// The filter menu takes string values, so "All" (null in the logic) gets a stand-in.
const ALL = 'all'

const WINDOW_OPTIONS: FilterOption<IngestionWarningsTimeWindow>[] = [
    { value: '24h', label: '24h' },
    { value: '7d', label: '7d' },
    { value: '30d', label: '30d' },
]

const SEVERITY_OPTIONS: FilterOption[] = [
    { value: ALL, label: 'All severities' },
    ...SEVERITIES.map((severity) => ({ value: severity, label: severity })),
]

/** The list's time range, severity and category, in the quill filter menu. */
export function QuillIngestionWarningsV2FilterMenu(): JSX.Element {
    const { filters, warnings } = useValues(ingestionWarningsV2Logic)
    const { setFilters } = useActions(ingestionWarningsV2Logic)

    // The API has no list of categories, so the menu offers the ones in the loaded warnings.
    const categoryOptions = useMemo<FilterOption[]>(() => {
        const categories = new Set(warnings.map((warning) => warning.category))
        if (filters.category) {
            categories.add(filters.category)
        }
        return [
            { value: ALL, label: 'All categories' },
            ...[...categories].sort().map((category) => ({ value: category, label: category })),
        ]
    }, [warnings, filters.category])

    const active = !!filters.category || !!filters.severity

    return (
        <DropdownMenu>
            <FilterMenuTrigger active={active} dataAttr="ingestion-warnings-v2-filter" />
            <DropdownMenuContent align="end" className="min-w-64">
                <FilterRadioSubMenu<IngestionWarningsTimeWindow>
                    label="Time range"
                    options={WINDOW_OPTIONS}
                    value={filters.window}
                    defaultValue="30d"
                    onChange={(window) => setFilters({ window })}
                />
                <DropdownMenuSeparator />
                <FilterRadioSubMenu
                    label="Severity"
                    options={SEVERITY_OPTIONS}
                    value={filters.severity ?? ALL}
                    defaultValue={ALL}
                    onChange={(severity) => setFilters({ severity: severity === ALL ? null : severity })}
                />
                <FilterRadioSubMenu
                    label="Category"
                    options={categoryOptions}
                    value={filters.category ?? ALL}
                    defaultValue={ALL}
                    onChange={(category) => setFilters({ category: category === ALL ? null : category })}
                />
                <FilterClearItem active={active} onClear={() => setFilters({ category: null, severity: null })} />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
