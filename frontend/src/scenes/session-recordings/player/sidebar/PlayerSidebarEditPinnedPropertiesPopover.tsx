import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPin, IconPinFilled } from '@posthog/icons'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'

import { sessionRecordingPinnedPropertiesLogic } from '../player-meta/sessionRecordingPinnedPropertiesLogic'
import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export type PlayerSidebarEditPinnedPropertiesPopoverProps = {
    logicPropsOverride?: SessionRecordingPlayerLogicProps
    onClose?: () => void
}

export function PlayerSidebarEditPinnedPropertiesPopover({
    logicPropsOverride,
}: PlayerSidebarEditPinnedPropertiesPopoverProps = {}): JSX.Element {
    const { logicProps: contextLogicProps } = useValues(sessionRecordingPlayerLogic)
    const { availableProperties } = useValues(playerMetaLogic(logicPropsOverride || contextLogicProps))
    const { pinnedProperties } = useValues(sessionRecordingPinnedPropertiesLogic)
    const { togglePropertyPin } = useActions(sessionRecordingPinnedPropertiesLogic)

    // Map pinned properties to selectedProperties format for TaxonomicFilter
    const selectedProperties = useMemo(() => {
        return {
            [TaxonomicFilterGroupType.PersonProperties]: pinnedProperties,
            [TaxonomicFilterGroupType.SessionProperties]: pinnedProperties,
        }
    }, [pinnedProperties])

    return (
        <>
            <div className="flex items-center gap-2 px-4 py-3">
                <IconPinFilled className="text-muted" />
                <h4 className="font-semibold m-0">Pinned overview properties</h4>
            </div>

            {availableProperties.length > 0 && (
                <div className="max-h-60 overflow-y-auto border-b px-2 pb-2">
                    <p className="text-muted text-xxs px-2 mb-1">On this recording</p>
                    {availableProperties.map((property) => (
                        <LemonButton
                            key={property.key}
                            fullWidth
                            size="small"
                            icon={pinnedProperties.includes(property.key) ? <IconPinFilled /> : <IconPin />}
                            onClick={() => togglePropertyPin(property.key)}
                        >
                            <PropertyKeyInfo value={property.key} type={property.type} disablePopover />
                        </LemonButton>
                    ))}
                </div>
            )}

            <LemonCollapse
                panels={[
                    {
                        key: 'all-properties',
                        header: 'Search all properties',
                        content: (
                            <TaxonomicFilter
                                taxonomicFilterLogicKey="pinned-properties-popover"
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.SessionProperties,
                                    TaxonomicFilterGroupType.PersonProperties,
                                ]}
                                selectedProperties={selectedProperties}
                                onChange={(_, propertyKey) => {
                                    togglePropertyPin(String(propertyKey))
                                }}
                            />
                        ),
                    },
                ]}
            />
        </>
    )
}
