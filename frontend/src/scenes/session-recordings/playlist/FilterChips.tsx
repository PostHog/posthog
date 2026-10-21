import { useActions, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { UniversalFilterButton } from 'lib/components/UniversalFilters/UniversalFilterButton'
import { humanFriendlyDurationFilter } from 'scenes/session-recordings/filters/DurationFilter'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { RecordingUniversalFilters } from '~/types'

import { filterLeaves, removeFilterLeaf } from './filterChipLeaves'

/** The applied conditions as removable chips: each filter, each duration bound, and the hidden-watched setting. */
export function FilterChips({
    filters,
    setFilters,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element | null {
    const { hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const leaves = filterLeaves(filters.filter_group)

    if (leaves.length === 0 && filters.duration.length === 0 && !hideViewedRecordings) {
        return null
    }

    return (
        <div className="flex items-center gap-1 flex-wrap min-w-0" data-attr="list-filter-chips">
            {leaves.map(({ path, filter }) => (
                <UniversalFilterButton
                    key={path.join('.')}
                    filter={filter}
                    onClose={() => setFilters({ filter_group: removeFilterLeaf(filters.filter_group, path) })}
                />
            ))}
            {filters.duration.map((duration, index) => (
                <LemonTag
                    key={`${duration.key}-${index}`}
                    closable
                    onClose={() => setFilters({ duration: filters.duration.filter((_, i) => i !== index) })}
                    data-attr="list-filter-chip-duration"
                >
                    {humanFriendlyDurationFilter(duration, duration.key)}
                </LemonTag>
            ))}
            {hideViewedRecordings && (
                <LemonTag
                    closable
                    onClose={() => setHideViewedRecordings(false)}
                    data-attr="list-filter-chip-unwatched"
                >
                    {hideViewedRecordings === 'any-user' ? 'Unwatched by anyone' : 'Unwatched'}
                </LemonTag>
            )}
        </div>
    )
}
