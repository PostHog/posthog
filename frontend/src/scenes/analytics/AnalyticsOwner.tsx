import { Avatar, AvatarFallback, Text, cn } from '@posthog/quill'

import { fullName } from 'lib/utils/strings'

import { AnalyticsItem } from './analyticsUtils'

function initials(owner: NonNullable<AnalyticsItem['createdBy']>): string {
    const name = fullName(owner)
    const letters = name === 'Unknown User' || !name ? owner.email : name
    return letters
        .split(/[\s@._-]+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0].toUpperCase())
        .join('')
}

export function AnalyticsOwnerAvatar({ owner }: { owner: NonNullable<AnalyticsItem['createdBy']> }): JSX.Element {
    return (
        <Avatar size="xs">
            <AvatarFallback>{initials(owner)}</AvatarFallback>
        </Avatar>
    )
}

/** Who created an item, as an avatar and name. Reads as a dash when the API knows no creator. */
export function AnalyticsOwner({
    owner,
    className,
}: {
    owner: AnalyticsItem['createdBy']
    className?: string
}): JSX.Element {
    if (!owner) {
        return (
            <Text size="xs" variant="muted" className={className}>
                –
            </Text>
        )
    }
    const name = fullName(owner) === 'Unknown User' ? owner.email : fullName(owner) || owner.email
    return (
        <span className={cn('flex min-w-0 items-center gap-2', className)}>
            <AnalyticsOwnerAvatar owner={owner} />
            <Text size="xs" className="truncate">
                {name}
            </Text>
        </span>
    )
}
