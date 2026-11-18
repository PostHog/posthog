import { BaseIcon, IconCheck, IconLogomark, IconVideoCamera } from '@posthog/icons'

import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu'

import { EventCategory } from '~/toolbar/shared/debug/eventCategories'

function checkableMenuItem(
    label: string,
    count: number | null,
    icon: JSX.Element | null,
    isActive: boolean,
    onClick: () => void
): LemonMenuItem {
    return {
        label: (
            <div className="w-full flex flex-row justify-between items-center">
                <div className="flex flex-row items-center gap-1">
                    {isActive ? <IconCheck /> : <BaseIcon />}
                    {icon}
                    {label}
                </div>
                {count !== null && (
                    <span
                        // without setting fontVariant to none a single digit number between brackets gets rendered as a ligature
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ fontVariant: 'none' }}
                    >
                        ({count})
                    </span>
                )}
            </div>
        ),
        active: isActive,
        onClick: onClick,
    }
}

export function eventTypeMenuItems(
    counts: Record<EventCategory, number>,
    selectedEventTypes: EventCategory[],
    setSelectedEventType: (eventType: EventCategory, enabled: boolean) => void
): LemonMenuItem[] {
    return [
        checkableMenuItem(
            'PostHog events',
            counts['posthog'],
            <IconLogomark />,
            selectedEventTypes.includes('posthog'),
            () => setSelectedEventType('posthog', !selectedEventTypes.includes('posthog'))
        ),
        checkableMenuItem(
            'Custom events',
            counts['custom'],
            <IconVideoCamera />,
            selectedEventTypes.includes('custom'),
            () => setSelectedEventType('custom', !selectedEventTypes.includes('custom'))
        ),
        checkableMenuItem(
            'Replay events',
            counts['snapshot'],
            <IconUnverifiedEvent />,
            selectedEventTypes.includes('snapshot'),
            () => setSelectedEventType('snapshot', !selectedEventTypes.includes('snapshot'))
        ),
    ]
}

export function hidePropertiesMenuItems(
    hidePostHogProperties: boolean,
    hidePostHogFlags: boolean,
    setHidePostHogProperties: (hide: boolean) => void,
    setHidePostHogFlags: (hide: boolean) => void
): LemonMenuItem[] {
    return [
        checkableMenuItem('Hide PostHog properties', null, null, hidePostHogProperties, () =>
            setHidePostHogProperties(!hidePostHogProperties)
        ),
        checkableMenuItem('Hide PostHog flags', null, null, hidePostHogFlags, () =>
            setHidePostHogFlags(!hidePostHogFlags)
        ),
    ]
}
