import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'

import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Popover } from 'lib/lemon-ui/Popover'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'

import { PropertyFilterType, PropertyOperator, RecordingUniversalFilters } from '~/types'

import { OverviewGrid, OverviewGridItem } from '../../components/OverviewGrid'
import { playlistLogic } from '../../playlist/playlistLogic'
import { sessionRecordingsPlaylistLogic } from '../../playlist/sessionRecordingsPlaylistLogic'
import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarEditPinnedPropertiesPopover } from './PlayerSidebarEditPinnedPropertiesPopover'

// Exported for testing
export function handleFilterByProperty(
    propertyKey: string,
    propertyValue: string | undefined,
    filters: RecordingUniversalFilters,
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void,
    setIsFiltersExpanded: (expanded: boolean) => void
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

    // Show toast notification with human-readable label and view filters button
    const filterLabel = formatPropertyLabel(filter, {})
    lemonToast.success(`Filter applied: ${filterLabel}`, {
        toastId: `filter-applied-${propertyKey}`,
        button: {
            label: 'View filters',
            action: () => {
                setIsFiltersExpanded(true)
            },
        },
    })
}

export function PlayerSidebarOverviewGrid({
    logicPropsOverride,
}: {
    logicPropsOverride?: SessionRecordingPlayerLogicProps
} = {}): JSX.Element {
    const { logicProps: contextLogicProps } = useValues(sessionRecordingPlayerLogic)
    const logicProps = logicPropsOverride || contextLogicProps
    const { displayOverviewItems, loading, isPropertyPopoverOpen } = useValues(playerMetaLogic(logicProps))
    const { setIsPropertyPopoverOpen } = useActions(playerMetaLogic(logicProps))
    const { filters } = useValues(sessionRecordingsPlaylistLogic)
    const { setFilters } = useActions(sessionRecordingsPlaylistLogic)
    const { setIsFiltersExpanded } = useActions(playlistLogic)

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
                                                  handleFilterByProperty(
                                                      item.property,
                                                      item.value,
                                                      filters,
                                                      setFilters,
                                                      setIsFiltersExpanded
                                                  )
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
