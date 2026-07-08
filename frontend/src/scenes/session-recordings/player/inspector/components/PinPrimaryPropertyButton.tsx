import { useActions, useValues } from 'kea'

import { IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { getPrimaryPropertyForEvent, hasTaxonomyPrimaryProperty } from 'lib/utils/events'

import { primaryEventPropertiesModel } from '~/models/primaryEventPropertiesModel'

export function PinPrimaryPropertyButton({
    eventName,
    propertyKey,
    isRowHovered,
}: {
    eventName: string
    propertyKey: string
    isRowHovered: boolean
}): JSX.Element | null {
    const { primaryProperties, primaryPropertiesLoading } = useValues(primaryEventPropertiesModel)
    const { updatePrimaryProperty } = useActions(primaryEventPropertiesModel)

    if (hasTaxonomyPrimaryProperty(eventName)) {
        if (getPrimaryPropertyForEvent(eventName) !== propertyKey) {
            return null
        }
        return (
            <LemonButton
                size="xsmall"
                noPadding
                active
                icon={<IconPinFilled />}
                disabledReason="Built-in primary property — can't be changed"
                data-attr="replay-pin-primary-property-builtin"
            />
        )
    }

    const currentPrimary = primaryProperties[eventName] ?? null
    const isPinned = currentPrimary === propertyKey

    const tooltip = isPinned
        ? `Unpin "${propertyKey}" — it will stop showing next to ${eventName} events`
        : currentPrimary
          ? `Pin "${propertyKey}" as the primary property, replacing "${currentPrimary}". Shown next to ${eventName} events for your whole team.`
          : `Pin "${propertyKey}" so its value always shows next to ${eventName} events — here and on the timeline. Applies for your whole team.`

    return (
        <LemonButton
            size="xsmall"
            noPadding
            active={isPinned}
            loading={primaryPropertiesLoading}
            icon={isPinned ? <IconPinFilled /> : <IconPin />}
            tooltip={tooltip}
            onClick={() => updatePrimaryProperty({ eventName, propertyKey: isPinned ? null : propertyKey })}
            className={isPinned || isRowHovered ? undefined : 'opacity-0 focus:opacity-100'}
            data-attr="replay-pin-primary-property"
        />
    )
}
