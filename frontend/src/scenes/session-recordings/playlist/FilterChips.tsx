import { useActions, useValues } from 'kea'
import { ReactNode, useState } from 'react'

import { IconClock, IconEye, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { UniversalFilterButton } from 'lib/components/UniversalFilters/UniversalFilterButton'
import { humanFriendlyDurationFilter } from 'scenes/session-recordings/filters/DurationFilter'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { RecordingUniversalFilters } from '~/types'

import { filterLeaves, removeFilterLeaf } from './filterChipLeaves'

const MAX_VISIBLE_CHIPS = 4

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
    const [expanded, setExpanded] = useState(false)
    const leaves = filterLeaves(filters.filter_group)

    const chips: ReactNode[] = [
        ...leaves.map(({ path, filter }) => (
            <UniversalFilterButton
                key={path.join('.')}
                filter={filter}
                onClose={() => setFilters({ filter_group: removeFilterLeaf(filters.filter_group, path) })}
            />
        )),
        ...filters.duration.map((duration, index) => (
            <FilterChip
                key={`${duration.key}-${index}`}
                icon={<IconClock />}
                onClose={() => setFilters({ duration: filters.duration.filter((_, i) => i !== index) })}
                dataAttr="list-filter-chip-duration"
            >
                {humanFriendlyDurationFilter(duration, duration.key)}
            </FilterChip>
        )),
        ...(hideViewedRecordings
            ? [
                  <FilterChip
                      key="unwatched"
                      icon={<IconEye />}
                      onClose={() => setHideViewedRecordings(false)}
                      dataAttr="list-filter-chip-unwatched"
                  >
                      {hideViewedRecordings === 'any-user' ? 'Unwatched by anyone' : 'Unwatched'}
                  </FilterChip>,
              ]
            : []),
    ]

    if (chips.length === 0) {
        return null
    }

    const hiddenCount = chips.length - MAX_VISIBLE_CHIPS
    const visible = expanded || hiddenCount <= 0 ? chips : chips.slice(0, MAX_VISIBLE_CHIPS)

    return (
        <div className="flex items-center gap-1 flex-wrap min-w-0" data-attr="list-filter-chips">
            {visible}
            {hiddenCount > 0 && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={() => setExpanded(!expanded)}
                    data-attr={expanded ? 'list-filter-chips-collapse' : 'list-filter-chips-expand'}
                >
                    {expanded ? 'Show less' : `+${hiddenCount} more`}
                </LemonButton>
            )}
        </div>
    )
}

function FilterChip({
    icon,
    onClose,
    dataAttr,
    children,
}: {
    icon: ReactNode
    onClose: () => void
    dataAttr: string
    children: ReactNode
}): JSX.Element {
    return (
        <div
            className="UniversalFilterButton UniversalFilterButton--closeable inline-flex items-center ph-no-capture"
            data-attr={dataAttr}
        >
            <div className="flex items-center flex-1 truncate gap-1">
                <span className="shrink-0 text-secondary">{icon}</span>
                <span className="truncate">{children}</span>
            </div>
            <LemonButton size="xsmall" icon={<IconX className="w-3 h-3" />} onClick={onClose} className="p-0.5" />
        </div>
    )
}
