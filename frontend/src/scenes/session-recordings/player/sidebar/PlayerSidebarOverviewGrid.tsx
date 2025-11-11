import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Popover } from 'lib/lemon-ui/Popover'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'

import { PropertyFilterType, PropertyOperator, RecordingUniversalFilters } from '~/types'

import { OverviewGrid, OverviewGridItem } from '../../components/OverviewGrid'
import { sessionRecordingsPlaylistLogic } from '../../playlist/sessionRecordingsPlaylistLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarEditPinnedPropertiesPopover } from './PlayerSidebarEditPinnedPropertiesPopover'

// Exported for testing
export function handleFilterByProperty(
    propertyKey: string,
    propertyValue: string | undefined,
    filters: RecordingUniversalFilters,
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
): void {
    // Validate property value
    if (propertyValue === undefined || propertyValue === null) {
        return
    }

    // Determine property filter type
    const isPersonProperty =
        propertyKey.startsWith('$geoip_') ||
        ['$browser', '$os', '$device_type', '$initial_device_type'].includes(propertyKey) ||
        !propertyKey.startsWith('$')

    const filterType = isPersonProperty ? PropertyFilterType.Person : PropertyFilterType.Session

    // Create property filter object
    const filter = {
        type: filterType,
        key: propertyKey,
        value: propertyValue,
        operator: PropertyOperator.Exact,
    }

    // Clone the current filter group structure and add to the first nested group
    const currentGroup = filters.filter_group
    const newGroup = {
        ...currentGroup,
        values: currentGroup.values.map((nestedGroup, index) => {
            // Add to the first nested group (index 0)
            if (index === 0 && 'values' in nestedGroup) {
                return {
                    ...nestedGroup,
                    values: [...nestedGroup.values, filter],
                }
            }
            return nestedGroup
        }),
    }

    setFilters({ filter_group: newGroup })
}

export function PlayerSidebarOverviewGrid(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { displayOverviewItems, loading, isPropertyPopoverOpen } = useValues(playerMetaLogic(logicProps))
    const { setIsPropertyPopoverOpen } = useActions(playerMetaLogic(logicProps))
    const { filters } = useValues(sessionRecordingsPlaylistLogic)
    const { setFilters } = useActions(sessionRecordingsPlaylistLogic)

    return (
        <>
            <div className="rounded border bg-surface-primary">
                {loading ? (
                    <div className="flex flex-col deprecated-space-y-1">
                        <LemonSkeleton.Row repeat={6} className="h-5" />
                    </div>
                ) : (
                    <OverviewGrid>
                        <Popover
                            visible={isPropertyPopoverOpen}
                            onClickOutside={() => setIsPropertyPopoverOpen(false)}
                            overlay={<PlayerSidebarEditPinnedPropertiesPopover />}
                            placement="bottom"
                        >
                            <LemonButton
                                icon={<IconGear />}
                                onClick={() => setIsPropertyPopoverOpen(!isPropertyPopoverOpen)}
                                fullWidth
                                size="small"
                                type="secondary"
                            >
                                Edit pinned overview properties
                            </LemonButton>
                        </Popover>
                        {displayOverviewItems.map((item) => {
                            return (
                                <OverviewGridItem
                                    key={item.label}
                                    description={item.valueTooltip}
                                    label={item.label}
                                    icon={item.icon}
                                    itemKeyTooltip={item.keyTooltip}
                                    fadeLabel
                                    showFilter={item.type === 'property' && item.value !== undefined}
                                    onFilterClick={
                                        item.type === 'property' && item.value !== undefined
                                            ? () =>
                                                  handleFilterByProperty(item.property, item.value, filters, setFilters)
                                            : undefined
                                    }
                                >
                                    <div className="flex flex-row items-center deprecated-space-x-2 justify-start font-medium">
                                        {item.type === 'property' && (
                                            <PropertyIcon property={item.property} value={item.value} />
                                        )}
                                        <span>{item.value}</span>
                                    </div>
                                </OverviewGridItem>
                            )
                        })}
                    </OverviewGrid>
                )}
            </div>
        </>
    )
}
