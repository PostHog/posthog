import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Popover } from 'lib/lemon-ui/Popover'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { OverviewGrid, OverviewGridItem } from '../../components/OverviewGrid'
import { sessionRecordingsPlaylistLogic } from '../../playlist/sessionRecordingsPlaylistLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarEditPinnedPropertiesPopover } from './PlayerSidebarEditPinnedPropertiesPopover'

// Exported for testing
export function handleFilterByProperty(
    propertyKey: string,
    propertyValue: string | undefined,
    setFilters: (filters: any) => void
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

    const filterType = isPersonProperty ? PropertyFilterType.Person : PropertyFilterType.Event

    // Create property filter object
    const filter = {
        type: filterType,
        key: propertyKey,
        value: propertyValue,
        operator: PropertyOperator.Exact,
    }

    // Apply filter
    if (isPersonProperty) {
        setFilters({ person_properties: [filter] })
    } else {
        setFilters({ session_properties: [filter] })
    }
}

export function PlayerSidebarOverviewGrid(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { displayOverviewItems, loading, isPropertyPopoverOpen } = useValues(playerMetaLogic(logicProps))
    const { setIsPropertyPopoverOpen } = useActions(playerMetaLogic(logicProps))
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
                                            ? () => handleFilterByProperty(item.property, item.value, setFilters)
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
