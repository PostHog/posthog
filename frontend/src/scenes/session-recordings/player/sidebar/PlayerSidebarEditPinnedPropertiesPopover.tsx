import { useActions, useValues } from 'kea'

import { IconPin, IconPinFilled, IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

import { playerMetaLogic } from '../player-meta/playerMetaLogic'
import { sessionRecordingPinnedPropertiesLogic } from '../player-meta/sessionRecordingPinnedPropertiesLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export type PlayerSidebarEditPinnedPropertiesPopoverProps = {
    onClose?: () => void
}

export function PlayerSidebarEditPinnedPropertiesPopover(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { filteredPropertiesWithInfo, propertySearchQuery } = useValues(playerMetaLogic(logicProps))
    const { setPropertySearchQuery } = useActions(playerMetaLogic(logicProps))
    const { pinnedProperties } = useValues(sessionRecordingPinnedPropertiesLogic)
    const { togglePropertyPin } = useActions(sessionRecordingPinnedPropertiesLogic)

    return (
        <div className="flex flex-col overflow-hidden max-h-96 w-[400px]">
            <div className="flex items-center gap-2 px-4 py-3 border-b">
                <IconPinFilled className="text-muted" />
                <h4 className="font-semibold m-0">Pinned properties</h4>
            </div>

            <div className="px-2 py-2 border-b">
                <LemonInput
                    placeholder="Search properties..."
                    value={propertySearchQuery}
                    onChange={setPropertySearchQuery}
                    prefix={<IconSearch />}
                    size="small"
                    fullWidth
                    autoFocus
                />
            </div>

            <ScrollableShadows direction="vertical" className="flex-1">
                <div className="flex flex-col">
                    {filteredPropertiesWithInfo.length === 0 ? (
                        <div className="px-4 py-8 text-center text-muted">
                            {propertySearchQuery.trim() ? 'No properties match your search' : 'No properties available'}
                        </div>
                    ) : (
                        filteredPropertiesWithInfo.map(({ propertyKey, propertyInfo }) => {
                            const isPinned = pinnedProperties.includes(propertyKey)

                            const handleToggle = (): void => {
                                togglePropertyPin(propertyKey)
                            }

                            return (
                                <LemonButton
                                    key={propertyKey}
                                    data-attr={
                                        isPinned ? 'session-overview-unpin-property' : 'session-overview-pin-property'
                                    }
                                    size="small"
                                    fullWidth
                                    className="justify-between"
                                    onClick={handleToggle}
                                    sideIcon={isPinned ? <IconPinFilled /> : <IconPin />}
                                    tooltip={
                                        propertyInfo.label !== propertyInfo.originalKey
                                            ? `Sent as: ${propertyInfo.originalKey}`
                                            : undefined
                                    }
                                >
                                    <span>{propertyInfo.label}</span>
                                </LemonButton>
                            )
                        })
                    )}
                </div>
            </ScrollableShadows>
        </div>
    )
}
