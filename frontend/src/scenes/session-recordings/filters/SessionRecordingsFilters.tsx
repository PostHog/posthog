import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { useActions, useValues } from 'kea'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { useMemo } from 'react'

import { RecordingFilters } from '~/types'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { getDefaultFilters } from '../playlist/sessionRecordingsPlaylistLogic'
import { AdvancedSessionRecordingsFilters } from './AdvancedSessionRecordingsFilters'
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
    const { prefersAdvancedFilters } = useValues(playerSettingsLogic)
    const { setPrefersAdvancedFilters } = useActions(playerSettingsLogic)

    const initiallyOpen = useMemo(() => {
        // advanced always open if not showing simple filters, saves computation
        if (hideSimpleFilters) {
            return true
        }
        const defaultFilters = getDefaultFilters()
        return prefersAdvancedFilters || !equal(advancedFilters, defaultFilters)
    }, [])

    const AdvancedFilters = (
        <AdvancedSessionRecordingsFilters
            filters={advancedFilters}
            setFilters={setAdvancedFilters}
            showPropertyFilters={showPropertyFilters}
        />
    )

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

            {hideSimpleFilters ? (
                AdvancedFilters
            ) : (
                <LemonCollapse
                    className="w-full rounded-none border-0 border-t"
                    multiple
                    defaultActiveKeys={initiallyOpen ? ['advanced-filters'] : []}
                    size="small"
                    onChange={(activeKeys) => {
                        setPrefersAdvancedFilters(activeKeys.includes('advanced-filters'))
                    }}
                    panels={[
                        {
                            key: 'advanced-filters',
                            header: 'Advanced filters',
                            className: 'p-0',
                            content: AdvancedFilters,
                        },
                    ]}
                />
            )}
        </div>
    )
}
