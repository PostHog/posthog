import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconDatabase } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { SelectedDatabase, directQueryLogic } from './directQueryLogic'

export function DatabaseSelector(): JSX.Element | null {
    const { selectedDatabase, databaseOptions, sourcesLoading, hasDirectQuerySources } = useValues(directQueryLogic)
    const { setSelectedDatabase, loadSources } = useActions(directQueryLogic)

    useEffect(() => {
        loadSources()
    }, [loadSources])

    // Don't show selector if there are no direct query sources
    if (!hasDirectQuerySources && !sourcesLoading) {
        return null
    }

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
                options={databaseOptions}
                loading={sourcesLoading}
                dropdownPlacement="bottom-start"
                className="min-w-[140px]"
            />
        </div>
    )
}
