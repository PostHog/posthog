import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPinFilled } from '@posthog/icons'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { sessionRecordingPinnedPropertiesLogic } from '../player-meta/sessionRecordingPinnedPropertiesLogic'

export type PlayerSidebarEditPinnedPropertiesPopoverProps = {
    onClose?: () => void
}

export function PlayerSidebarEditPinnedPropertiesPopover(): JSX.Element {
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
            <div className="flex items-center gap-2 px-4 py-3 border-b">
                <IconPinFilled className="text-muted" />
                <h4 className="font-semibold m-0">Pinned overview properties</h4>
            </div>

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
        </>
    )
}
