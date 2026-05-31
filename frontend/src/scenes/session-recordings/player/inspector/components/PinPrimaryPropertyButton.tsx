import { useActions, useValues } from 'kea'

import { IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { getPrimaryPropertyForEvent, hasTaxonomyPrimaryProperty } from 'lib/utils/primaryEventProperty'

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
    const { primaryProperties, savingPrimaryPropertyForEvents } = useValues(primaryEventPropertiesModel)
    const { setPrimaryProperty } = useActions(primaryEventPropertiesModel)

    if (hasTaxonomyPrimaryProperty(eventName)) {
        if (getPrimaryPropertyForEvent(eventName) !== propertyKey) {
            return null
        }
        return (
            <LemonButton
                size="xsmall"
                noPadding
                icon={<IconPinFilled />}
                disabledReason="Built-in primary property — can't be changed"
            />
        )
    }

    const currentPrimary = primaryProperties[eventName] ?? null
    const isPinned = currentPrimary === propertyKey
    const saving = savingPrimaryPropertyForEvents.includes(eventName)

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
            loading={saving}
            icon={isPinned ? <IconPinFilled /> : <IconPin />}
            tooltip={tooltip}
            onClick={() => setPrimaryProperty(eventName, isPinned ? null : propertyKey)}
            className={isPinned || isRowHovered ? undefined : 'opacity-0 focus:opacity-100'}
        />
    )
}
