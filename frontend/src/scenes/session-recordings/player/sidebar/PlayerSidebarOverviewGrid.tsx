import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Popover } from 'lib/lemon-ui/Popover'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'

import { OverviewGrid, OverviewGridItem } from '../../components/OverviewGrid'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarEditPinnedPropertiesPopover } from './PlayerSidebarEditPinnedPropertiesPopover'

export function PlayerSidebarOverviewGrid(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { displayOverviewItems, loading, sessionPerson, isPropertyPopoverOpen } = useValues(
        playerMetaLogic(logicProps)
    )
    const { setIsPropertyPopoverOpen } = useActions(playerMetaLogic(logicProps))

    return (
        <>
            <div className="rounded border bg-surface-primary">
                {loading ? (
                    <div className="flex flex-col deprecated-space-y-1">
                        <LemonSkeleton.Row repeat={6} className="h-5" />
                    </div>
                ) : (
                    <OverviewGrid>
                        {displayOverviewItems.map((item) => {
                            return (
                                <OverviewGridItem
                                    key={item.label}
                                    description={item.valueTooltip}
                                    label={item.label}
                                    icon={item.icon}
                                    itemKeyTooltip={item.keyTooltip}
                                    fadeLabel
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
                <div className="px-2 py-2 border-t">
                    <Popover
                        visible={isPropertyPopoverOpen}
                        onClickOutside={() => setIsPropertyPopoverOpen(false)}
                        overlay={
                            sessionPerson?.distinct_ids?.[0] || sessionPerson?.id ? (
                                <PlayerSidebarEditPinnedPropertiesPopover
                                    distinctId={sessionPerson?.distinct_ids?.[0]}
                                    personId={sessionPerson?.id}
                                    onClose={() => setIsPropertyPopoverOpen(false)}
                                />
                            ) : null
                        }
                        placement="bottom"
                        fallbackPlacements={['top', 'right']}
                        showArrow
                    />
                    <LemonButton
                        icon={<IconGear />}
                        onClick={() => setIsPropertyPopoverOpen(true)}
                        fullWidth
                        size="small"
                        type="secondary"
                    >
                        Edit pinned overview properties
                    </LemonButton>
                </div>
            </div>
        </>
    )
}
