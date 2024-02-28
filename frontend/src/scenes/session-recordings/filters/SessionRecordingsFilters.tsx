import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { useMemo } from 'react'

import { RecordingFilters } from '~/types'

import { getDefaultFilters } from '../playlist/sessionRecordingsPlaylistLogic'
import { AdvancedSessionRecordingsFilters } from './AdvancedSessionRecordingsFilters'
import { OrderingFilters } from './OrderingFilters'
import { SimpleSessionRecordingsFilters } from './SimpleSessionRecordingsFilters'

interface SessionRecordingsFiltersProps {
    advancedFilters: RecordingFilters
    simpleFilters: RecordingFilters
    setAdvancedFilters: (filters: RecordingFilters) => void
    setSimpleFilters: (filters: RecordingFilters) => void
    showPropertyFilters?: boolean
    hideSimpleFilters?: boolean
    onReset?: () => void
}

export function SessionRecordingsFilters({
    advancedFilters,
    simpleFilters,
    setAdvancedFilters,
    setSimpleFilters,
    showPropertyFilters,
    hideSimpleFilters,
    onReset,
}: SessionRecordingsFiltersProps): JSX.Element {
    const initiallyOpen = useMemo(() => {
        // advanced always open if not showing simple filters, saves computation
        if (hideSimpleFilters) {
            return true
        }
        const defaultFilters = getDefaultFilters()
        return !equal(advancedFilters, defaultFilters)
    }, [])
    const hasFilterOrdering = useFeatureFlag('SESSION_REPLAY_FILTER_ORDERING')

    const AdvancedFilters = (
        <AdvancedSessionRecordingsFilters
            filters={advancedFilters}
            setFilters={setAdvancedFilters}
            showPropertyFilters={showPropertyFilters}
        />
    )

    const panels = [
        !hideSimpleFilters && {
            key: 'advanced-filters',
            header: 'Advanced filters',
            className: 'p-0',
            content: AdvancedFilters,
        },
        hasFilterOrdering && {
            key: 'ordering',
            header: 'Ordering',
            content: <OrderingFilters />,
        },
    ].filter(Boolean)

    return (
        <div className="relative flex flex-col">
            <div className="space-y-1 p-3">
                <div className="flex justify-between">
                    <LemonLabel>Find sessions:</LemonLabel>

                    {onReset && (
                        <span className="absolute top-2 right-2">
                            <LemonButton size="small" onClick={onReset}>
                                Reset
                            </LemonButton>
                        </span>
                    )}
                </div>

                {!hideSimpleFilters && (
                    <SimpleSessionRecordingsFilters filters={simpleFilters} setFilters={setSimpleFilters} />
                )}
            </div>

            {hideSimpleFilters && AdvancedFilters}

            {panels.length > 0 && (
                <LemonCollapse
                    className="w-full rounded-none border-0 border-t"
                    multiple
                    defaultActiveKeys={initiallyOpen ? ['advanced-filters'] : []}
                    size="small"
                    panels={panels}
                />
            )}
        </div>
    )
}
