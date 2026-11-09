import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, Skeleton } from '@posthog/quill'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { PlayerSidebarEditPinnedPropertiesPopover } from 'scenes/session-recordings/player/sidebar/PlayerSidebarEditPinnedPropertiesPopover'
import {
    overviewPropertyFilterType,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { PropertyOperator, UniversalFiltersGroup } from '~/types'

import { OverviewItem } from '../../components/OverviewGrid'
import { OverviewFilterState, QuillOverviewRow } from './QuillOverviewRow'

function filterStateFor(
    filterGroup: UniversalFiltersGroup,
    propertyKey: string,
    propertyValue: string | undefined
): OverviewFilterState {
    const filterType = overviewPropertyFilterType(propertyKey)
    // Filters are added to the first nested group.
    const firstNestedGroup = filterGroup.values[0]
    if (!firstNestedGroup || !('values' in firstNestedGroup)) {
        return 'inactive'
    }
    const sameKey = firstNestedGroup.values.filter(
        (filter) =>
            'key' in filter &&
            'type' in filter &&
            'operator' in filter &&
            filter.type === filterType &&
            filter.key === propertyKey &&
            filter.operator === PropertyOperator.Exact
    )
    if (sameKey.some((filter) => 'value' in filter && filter.value === propertyValue)) {
        return 'active'
    }
    return sameKey.length > 0 ? 'replace' : 'inactive'
}

export function QuillOverviewRows({
    items,
    pickerGroupType,
    leadingRows,
}: {
    items: OverviewItem[]
    /** Property group the "Add property" picker opens on. */
    pickerGroupType: TaxonomicFilterGroupType.SessionProperties | TaxonomicFilterGroupType.PersonProperties
    leadingRows?: JSX.Element
}): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { loading, isPropertyPopoverOpen } = useValues(playerMetaLogic(logicProps))
    const { setIsPropertyPopoverOpen } = useActions(playerMetaLogic(logicProps))
    const { togglePropertyFilter } = useActions(sessionRecordingsPlaylistLogic)
    const { filters } = useValues(sessionRecordingsPlaylistLogic)
    // The open flag is shared by every rows table on screen, so each table also remembers whether it was the one opened.
    const [opened, setOpened] = useState(false)

    if (loading) {
        return (
            <div className="rounded border border-border bg-card flex flex-col gap-1 px-2 py-1">
                {Array.from({ length: Math.max(items.length, 2) }, (_, index) => (
                    <Skeleton key={index} className="h-5" />
                ))}
            </div>
        )
    }

    return (
        <div className="rounded border border-border bg-card flex flex-col divide-y divide-border">
            {leadingRows}
            {items.map((item) => {
                const filterable =
                    item.type === 'property' && item.value !== undefined && item.value !== null && item.value !== '-'
                return (
                    <QuillOverviewRow
                        key={item.type === 'property' ? item.property : item.label}
                        label={item.label}
                        icon={item.icon}
                        keyTooltip={item.keyTooltip}
                        valueTooltip={item.valueTooltip}
                        copyValue={filterable && item.property === '$ip' ? item.value : undefined}
                        filterState={
                            item.type !== 'property' || item.value === undefined
                                ? undefined
                                : filterable
                                  ? filterStateFor(filters.filter_group, item.property, item.value)
                                  : 'inactive'
                        }
                        filterDisabledReason={
                            item.type === 'property' && item.value !== undefined && !filterable
                                ? 'Cannot filter for missing values'
                                : undefined
                        }
                        onFilterClick={
                            item.type === 'property' && filterable
                                ? () => togglePropertyFilter(item.property, item.value)
                                : undefined
                        }
                    >
                        <span className="flex items-center gap-2 font-medium min-w-0">
                            {item.type === 'property' && <PropertyIcon property={item.property} value={item.value} />}
                            <span className="truncate">{item.value}</span>
                        </span>
                    </QuillOverviewRow>
                )
            })}
            <Popover
                open={opened && isPropertyPopoverOpen}
                onOpenChange={(open) => {
                    setOpened(open)
                    setIsPropertyPopoverOpen(open)
                }}
            >
                <PopoverTrigger
                    render={
                        <Button
                            size="xs"
                            className="w-full rounded-t-none justify-center"
                            data-attr="player-overview-property-popover-toggle"
                        />
                    }
                >
                    <IconPlus />
                    Add property
                </PopoverTrigger>
                <PopoverContent align="center" className="w-auto p-0">
                    <div data-not-quill>
                        <PlayerSidebarEditPinnedPropertiesPopover initialGroupType={pickerGroupType} />
                    </div>
                </PopoverContent>
            </Popover>
        </div>
    )
}
