import { useActions } from 'kea'

import {
    Avatar,
    AvatarFallback,
    AvatarGroup,
    AvatarImage,
    Dot,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { gravatarUrl } from 'lib/utils/gravatar'
import { fullNameOrEmail } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { TodaySpaceAuthor, authorInitials } from './todaySpaceAuthors'
import { TodayPresenceSurface, todaySpacesLogic } from './todaySpacesLogic'
import { shortTimeAgo } from './todayWorkItems'

const MAX_AVATARS = 3

interface TodaySpacePresenceProps {
    spaceId: string
    authors: TodaySpaceAuthor[]
    surface: TodayPresenceSurface
}

export function TodaySpacePresence({ spaceId, authors, surface }: TodaySpacePresenceProps): JSX.Element | null {
    const { openSpaceFromPresence } = useActions(todaySpacesLogic)
    if (!authors.length) {
        return null
    }
    const shown = authors.slice(0, MAX_AVATARS)
    const hiddenCount = authors.length - shown.length
    const liveCount = authors.filter((author) => author.live).length
    const people = `${authors.length} ${authors.length === 1 ? 'person' : 'people'}`
    const label = liveCount > 0 ? `${liveCount} of ${people} active now` : `${people} worked here recently`

    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <LinkPrimitive
                        to={urls.taskSpace(spaceId)}
                        onClick={() => openSpaceFromPresence(spaceId, surface)}
                        aria-label={label}
                        className="flex shrink-0 items-center gap-1 rounded-sm px-0.5"
                        data-attr="today-space-presence"
                    />
                }
            >
                {liveCount > 0 && <Dot variant="success" aria-hidden />}
                <AvatarGroup stacked reverse size="xs">
                    {shown.map((author) => (
                        <Avatar key={author.user.id}>
                            {author.user.email && <AvatarImage src={gravatarUrl(author.user.email)} alt="" />}
                            <AvatarFallback>{authorInitials(fullNameOrEmail(author.user))}</AvatarFallback>
                        </Avatar>
                    ))}
                </AvatarGroup>
                {hiddenCount > 0 && (
                    <Text render={<span />} size="xs" variant="muted" translate="no">
                        {`+${hiddenCount}`}
                    </Text>
                )}
            </TooltipTrigger>
            <TooltipContent>
                <div className="flex flex-col gap-0.5">
                    {authors.map((author) => (
                        <span key={author.user.id}>
                            {`${fullNameOrEmail(author.user)} · ${
                                author.live ? 'active now' : `active ${shortTimeAgo(author.lastActivityAt)} ago`
                            }`}
                        </span>
                    ))}
                </div>
            </TooltipContent>
        </Tooltip>
    )
}
