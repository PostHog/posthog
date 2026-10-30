import { useActions, useValues } from 'kea'
import { ReactNode, useState } from 'react'

import { IconClock, IconEye, IconPerson, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { convertSecondsToDuration } from 'lib/components/DurationPicker/DurationPicker'
import { UniversalFilterButton } from 'lib/components/UniversalFilters/UniversalFilterButton'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { PropertyOperator, RecordingDurationFilter, RecordingUniversalFilters } from '~/types'

import { asDisplay } from 'products/persons/frontend/person-utils'

import { filterLeaves, removeFilterLeaf } from './filterChipLeaves'
import { defaultRecordingDurationFilter, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

const MAX_VISIBLE_CHIPS = 4

const DURATION_TYPE_LABEL: Record<RecordingDurationFilter['key'], string> = {
    duration: '',
    active_seconds: ' active',
    inactive_seconds: ' inactive',
}

function compactDurationLabel(duration: RecordingDurationFilter): string {
    const operator = duration.operator === PropertyOperator.GreaterThan ? '>' : '<'
    const { timeValue, unit } = convertSecondsToDuration(duration.value || 0)
    return `${operator} ${timeValue}${unit[0]}${DURATION_TYPE_LABEL[duration.key]}`
}

function isDefaultDuration(duration: RecordingDurationFilter): boolean {
    return (
        duration.key === defaultRecordingDurationFilter.key &&
        duration.value === defaultRecordingDurationFilter.value &&
        duration.operator === defaultRecordingDurationFilter.operator
    )
}

export function FilterChips({
    filters,
    setFilters,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element | null {
    const { hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { recordings } = useValues(sessionRecordingsPlaylistLogic)
    const { filterByPerson } = useActions(sessionRecordingsPlaylistLogic)
    const [expanded, setExpanded] = useState(false)
    const leaves = filterLeaves(filters.filter_group)
    const filteredPerson = recordings.find((r) => r.person?.uuid === filters.person_uuid)?.person

    const chips: ReactNode[] = [
        ...leaves.map(({ path, filter }) => (
            <UniversalFilterButton
                key={path.join('.')}
                filter={filter}
                onClose={() => setFilters({ filter_group: removeFilterLeaf(filters.filter_group, path) })}
            />
        )),
        ...filters.duration.flatMap((duration, index) =>
            isDefaultDuration(duration)
                ? []
                : [
                      <FilterChip
                          key={`${duration.key}-${index}`}
                          icon={<IconClock />}
                          onClose={() =>
                              setFilters({
                                  duration: filters.duration.map((d, i) =>
                                      i === index ? defaultRecordingDurationFilter : d
                                  ),
                              })
                          }
                          dataAttr="list-filter-chip-duration"
                      >
                          {compactDurationLabel(duration)}
                      </FilterChip>,
                  ]
        ),
        ...(filters.person_uuid
            ? [
                  <FilterChip
                      key="person"
                      icon={<IconPerson />}
                      onClose={() => filterByPerson(null)}
                      dataAttr="list-filter-chip-person"
                  >
                      {filteredPerson ? asDisplay(filteredPerson) : 'One person'}
                  </FilterChip>,
              ]
            : []),
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
