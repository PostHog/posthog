import { Avatar, AvatarFallback, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { fullName } from 'lib/utils/strings'

import { UserBasicType } from '~/types'

/** `first_name` is optional so a generated `UserBasicApi` fits without an adapter. */
type Owner = Pick<UserBasicType, 'email'> & { first_name?: string; last_name?: string }

function initials(owner: Owner): string {
    const name = fullName(owner)
    const letters = name === 'Unknown User' || !name ? owner.email : name
    return letters
        .split(/[\s@._-]+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0].toUpperCase())
        .join('')
}

export function AnalyticsOwnerAvatar({ owner }: { owner: Owner }): JSX.Element {
    return (
        <Avatar size="xs">
            <AvatarFallback>{initials(owner)}</AvatarFallback>
        </Avatar>
    )
}

/** Who created an item, as an avatar and first name with the full name on hover. A dash when the API knows no creator. */
export function AnalyticsOwner({ owner, className }: { owner: Owner | null; className?: string }): JSX.Element {
    if (!owner) {
        return (
            <Text size="xs" variant="muted" className={className}>
                –
            </Text>
        )
    }
    const full = fullName(owner)
    const label = owner.first_name?.trim() || owner.email.split('@')[0]
    return (
        <Tooltip>
            <TooltipTrigger render={<span className={cn('flex min-w-0 items-center gap-1.5', className)} />}>
                <AnalyticsOwnerAvatar owner={owner} />
                <Text size="xs" className="truncate">
                    {label}
                </Text>
            </TooltipTrigger>
            <TooltipContent>{full && full !== 'Unknown User' ? full : owner.email}</TooltipContent>
        </Tooltip>
    )
}
