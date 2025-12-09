import { useActions, useValues } from 'kea'

import { IconDatabase } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { SelectedDatabase, directQueryLogic } from './directQueryLogic'

export function DatabaseSelector(): JSX.Element | null {
    const { selectedDatabase, databaseOptions, sourcesLoading, hasDirectQuerySources, selectedSourceName } =
        useValues(directQueryLogic)
    const { setSelectedDatabase } = useActions(directQueryLogic)

    // Check if selected database is a source ID that's not yet in our loaded options
    const selectedOptionExists = databaseOptions.some((opt) => opt.value === selectedDatabase)
    const isWaitingForSources = selectedDatabase !== 'hogql' && !selectedOptionExists && sourcesLoading

    // Don't show selector if there are no direct query sources (and we're done loading)
    if (!hasDirectQuerySources && !sourcesLoading && selectedDatabase === 'hogql') {
        return null
    }

    // Build options with a temporary option for the selected source if needed
    const displayOptions = isWaitingForSources
        ? [...databaseOptions, { value: selectedDatabase, label: selectedSourceName || 'Loading...' }]
        : databaseOptions

    return (
        <div className="flex items-center gap-1 px-2">
            <IconDatabase className="w-3 h-3 text-muted" />
            <LemonSelect
                size="xsmall"
                value={selectedDatabase}
                onChange={(value: SelectedDatabase | null) => {
                    if (value) {
                        setSelectedDatabase(value)
                    }
                }}
                options={displayOptions}
                loading={sourcesLoading}
                dropdownPlacement="bottom-start"
                className="min-w-[140px]"
            />
        </div>
    )
}
