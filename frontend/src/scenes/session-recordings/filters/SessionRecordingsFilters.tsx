import { LemonButton } from '@posthog/lemon-ui'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'

import { RecordingFilters } from '~/types'

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

            <AdvancedSessionRecordingsFilters
                filters={advancedFilters}
                setFilters={setAdvancedFilters}
                showPropertyFilters={showPropertyFilters}
            />
        </div>
    )
}
