import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Popover } from 'lib/lemon-ui/Popover'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'

import { PropertyOperator, UniversalFiltersGroup } from '~/types'

import { OverviewGrid, OverviewGridItem } from '../../components/OverviewGrid'
import { sessionRecordingsPlaylistLogic } from '../../playlist/sessionRecordingsPlaylistLogic'
import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarEditPinnedPropertiesPopover } from './PlayerSidebarEditPinnedPropertiesPopover'

function getFilterState(
    filterGroup: UniversalFiltersGroup,
    propertyKey: string,
    propertyValue: string | undefined
): 'active' | 'replace' | 'inactive' {
    // Check first nested group (index 0) where filters are added
    const firstNestedGroup = filterGroup.values[0]
    if (!firstNestedGroup || !('values' in firstNestedGroup)) {
        return 'inactive'
    }

    // Check if exact match exists
    const hasExactMatch = firstNestedGroup.values.some((filter) => {
        if ('key' in filter && 'value' in filter && 'type' in filter && 'operator' in filter) {
            return (
                filter.key === propertyKey &&
                filter.value === propertyValue &&
                filter.operator === PropertyOperator.Exact
            )
        }
        return false
    })

    if (hasExactMatch) {
        return 'active'
    }

    // Check if same key with different value exists
    const hasSameKey = firstNestedGroup.values.some((filter) => {
        if ('key' in filter && 'type' in filter && 'operator' in filter) {
            return filter.key === propertyKey && filter.operator === PropertyOperator.Exact
        }
        return false
    })

    return hasSameKey ? 'replace' : 'inactive'
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
    const { togglePropertyFilter } = useActions(sessionRecordingsPlaylistLogic)
    const { filters } = useValues(sessionRecordingsPlaylistLogic)

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
                            const isFilterable =
                                item.type === 'property' &&
                                item.value !== undefined &&
                                item.value !== null &&
                                item.value !== '-'
                            const filterDisabledReason =
                                item.type === 'property' && item.value !== undefined && !isFilterable
                                    ? 'Cannot filter for missing values'
                                    : undefined

                            const filterState =
                                item.type === 'property' && isFilterable
                                    ? getFilterState(filters.filter_group, item.property, item.value)
                                    : 'inactive'

                            return (
                                <OverviewGridItem
                                    key={item.label}
                                    description={item.valueTooltip}
                                    label={item.label}
                                    icon={item.icon}
                                    itemKeyTooltip={item.keyTooltip}
                                    fadeLabel
                                    showFilter={item.type === 'property' && item.value !== undefined}
                                    filterDisabledReason={filterDisabledReason}
                                    filterState={filterState}
                                    onFilterClick={
                                        isFilterable ? () => togglePropertyFilter(item.property, item.value) : undefined
                                    }
                                >
                                    <div className="flex flex-row items-center deprecated-space-x-2 justify-start font-medium min-w-0">
                                        {item.type === 'property' && (
                                            <PropertyIcon property={item.property} value={item.value} />
                                        )}
                                        <span className="truncate">{item.value}</span>
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
