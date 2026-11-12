import { ReactNode } from 'react'

import { Avatar, AvatarFallback, AvatarImage, Text } from '@posthog/quill'

import { QuillHoverCard } from 'lib/components/QuillHoverCard/QuillHoverCard'
import { gravatarUrl } from 'lib/utils/gravatar'

import { UserBasicType } from '~/types'

interface QuillMemberHoverCardProps {
    /** Absent for authors outside the project, such as a Slack user, whose name then shows without a card. */
    user: UserBasicType | null | undefined
    children: ReactNode
}

export function QuillMemberHoverCard({ user, children }: QuillMemberHoverCardProps): JSX.Element {
    if (!user) {
        return <>{children}</>
    }

    const name = [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email

    return (
        <QuillHoverCard
            align="start"
            className="w-auto max-w-xs flex-row items-center gap-2 p-2"
            content={
                <>
                    <Avatar size="lg">
                        {user.email && <AvatarImage src={gravatarUrl(user.email)} alt="" />}
                        <AvatarFallback>{name.slice(0, 1)}</AvatarFallback>
                    </Avatar>
                    <div className="ph-no-capture flex min-w-0 flex-col">
                        <Text weight="semibold" className="truncate">
                            {name}
                        </Text>
                        {user.email && (
                            <Text size="xs" variant="muted" className="truncate select-text">
                                {user.email}
                            </Text>
                        )}
                    </div>
                </>
            }
        >
            {children}
        </QuillHoverCard>
    )
}
