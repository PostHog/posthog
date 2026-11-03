import { IconLogomark } from '@posthog/icons'
import { Avatar, AvatarFallback, AvatarImage } from '@posthog/quill'

import { gravatarUrl } from 'lib/utils/gravatar'

interface QuillPersonAvatarProps {
    name: string
    email?: string
    size?: 'xs' | 'sm' | 'default'
    /** PostHog itself, or staff acting as the user, rather than a person. */
    system?: boolean
}

export function QuillPersonAvatar({ name, email, size = 'sm', system }: QuillPersonAvatarProps): JSX.Element {
    if (system) {
        return (
            <Avatar size={size}>
                <AvatarFallback>
                    <IconLogomark />
                </AvatarFallback>
            </Avatar>
        )
    }
    return (
        <Avatar size={size} className="ph-no-capture">
            {email && <AvatarImage src={gravatarUrl(email)} alt="" />}
            <AvatarFallback>{(name || email || '?').charAt(0).toUpperCase()}</AvatarFallback>
        </Avatar>
    )
}
