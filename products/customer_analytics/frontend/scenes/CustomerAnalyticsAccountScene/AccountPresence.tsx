import { useValues } from 'kea'

import { ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

const MAX_PRESENCE_AVATARS = 5

function formatViewerNames(names: string[]): string {
    if (names.length === 1) {
        return names[0] ?? ''
    }
    if (names.length === 2) {
        return `${names[0]} and ${names[1]}`
    }
    return `${names.slice(0, -1).join(', ')}, and ${names.at(-1) ?? ''}`
}

function presenceTooltip(displayNames: string[], viewerCount: number): string {
    const overflowCount = viewerCount - displayNames.length
    const names =
        overflowCount > 0 ? `${displayNames.join(', ')}, and ${overflowCount} more` : formatViewerNames(displayNames)
    return `${names} ${viewerCount === 1 ? 'is' : 'are'} viewing this account`
}

export function AccountPresence(): JSX.Element | null {
    const { accountPresenceViewers } = useValues(customerAnalyticsAccountSceneLogic)

    if (!accountPresenceViewers.length) {
        return null
    }

    const shownViewers = accountPresenceViewers.slice(0, MAX_PRESENCE_AVATARS)
    const tooltip = presenceTooltip(
        shownViewers.map((viewer) => viewer.display_name),
        accountPresenceViewers.length
    )

    return (
        <Tooltip title={tooltip}>
            <div className="ProfileBubbles self-center" aria-label={tooltip}>
                {shownViewers.map((viewer, index) => (
                    <ProfilePicture
                        key={viewer.user_id}
                        name={viewer.display_name}
                        title={viewer.display_name}
                        size="md"
                        index={index}
                    />
                ))}
                {accountPresenceViewers.length > shownViewers.length ? (
                    <div className="ProfileBubbles__more">+{accountPresenceViewers.length - shownViewers.length}</div>
                ) : null}
            </div>
        </Tooltip>
    )
}
