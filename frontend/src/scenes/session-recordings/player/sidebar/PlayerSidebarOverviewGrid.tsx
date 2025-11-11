import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Popover } from 'lib/lemon-ui/Popover'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { applyRecordingPropertyFilter } from 'scenes/session-recordings/utils'

import { OverviewGrid, OverviewGridItem } from '../../components/OverviewGrid'
import { playlistLogic } from '../../playlist/playlistLogic'
import { sessionRecordingsPlaylistLogic } from '../../playlist/sessionRecordingsPlaylistLogic'
import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarEditPinnedPropertiesPopover } from './PlayerSidebarEditPinnedPropertiesPopover'

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
                                                  applyRecordingPropertyFilter(
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
