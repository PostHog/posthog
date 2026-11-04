import { Avatar, AvatarFallback, AvatarImage } from '@posthog/quill'

import { gravatarUrl } from 'lib/utils/gravatar'

export interface AvatarUser {
    email?: string | null
    first_name?: string | null
    last_name?: string | null
}

function initials(user: AvatarUser): string {
    const name = [user.first_name, user.last_name].filter(Boolean).join(' ').trim()
    const source = name || user.email || '?'
    return source
        .split(/[\s@._-]+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase() ?? '')
        .join('')
}

/** A person's gravatar with their initials behind it, for comment and viewer lists. */
export function QuillUserAvatar({
    user,
    size = 'sm',
    className,
}: {
    user: AvatarUser | null | undefined
    size?: 'xs' | 'sm' | 'default'
    className?: string
}): JSX.Element {
    const email = user?.email ?? undefined
    return (
        <Avatar size={size} className={className}>
            {email && <AvatarImage src={gravatarUrl(email)} alt="" />}
            <AvatarFallback>{user ? initials(user) : '?'}</AvatarFallback>
        </Avatar>
    )
}
