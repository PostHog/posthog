import React from 'react'

import { Avatar, AvatarFallback, AvatarImage, cn } from '@posthog/quill'

import { IconRobot } from '../icons'

type ProfilePictureSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'xxl'

// quill has four avatar sizes, so the Lemon sizes outside them keep their own dimensions.
const AVATAR_SIZES: Record<ProfilePictureSize, { size: 'xs' | 'sm' | 'default' | 'lg'; className?: string }> = {
    xs: { size: 'xs', className: 'size-4' },
    sm: { size: 'xs' },
    md: { size: 'sm' },
    lg: { size: 'default' },
    xl: { size: 'lg', className: 'size-10 text-base' },
    xxl: { size: 'lg', className: 'size-12 text-xl' },
}

export interface QuillProfilePictureProps {
    nameAndEmail: string | undefined
    gravatarUrl: string | undefined
    /** The user's hedgehog avatar, rendered in place of their initial or gravatar. */
    hedgehogAvatar: React.ReactNode
    size: ProfilePictureSize
    type: 'person' | 'bot' | 'system'
    title?: string
    className?: string
    /** Shown beside the picture when set. */
    displayName?: string
}

export const QuillProfilePicture = React.forwardRef<HTMLSpanElement, QuillProfilePictureProps>(
    function QuillProfilePicture(
        { nameAndEmail, gravatarUrl, hedgehogAvatar, size, type, title, className, displayName },
        ref
    ) {
        const avatarSize = AVATAR_SIZES[size]
        const initial = nameAndEmail ? String.fromCodePoint(nameAndEmail.codePointAt(0)!).toLocaleUpperCase() : '?'

        const avatar = (
            <Avatar ref={ref} size={avatarSize.size} className={cn('ph-no-capture', avatarSize.className, className)}>
                {hedgehogAvatar ? (
                    hedgehogAvatar
                ) : (
                    <>
                        {gravatarUrl && (
                            <AvatarImage
                                src={gravatarUrl}
                                title={title || `This is the Gravatar for ${nameAndEmail}`}
                                alt=""
                            />
                        )}
                        <AvatarFallback>{type === 'bot' ? <IconRobot /> : initial}</AvatarFallback>
                    </>
                )}
            </Avatar>
        )

        if (displayName === undefined) {
            return avatar
        }

        return (
            <span className="inline-flex min-w-0 items-center gap-1.5" title={nameAndEmail}>
                {avatar}
                <span className="ph-no-capture min-w-0 truncate">{displayName}</span>
            </span>
        )
    }
)
