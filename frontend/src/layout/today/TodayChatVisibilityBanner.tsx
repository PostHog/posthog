import { useValues } from 'kea'

import { IconGlobe, IconPeople } from '@posthog/icons'
import { Item, ItemContent, ItemDescription, ItemMedia } from '@posthog/quill'

import { userLogic } from 'scenes/userLogic'

import { chatVisibility } from './todayChatVisibility'
import { todaySessionMenuLogic } from './todaySessionMenuLogic'
import { todaySpacesLogic } from './todaySpacesLogic'

interface TodayChatVisibilityBannerProps {
    taskId: string
    spaceId: string | null
    ownerId: number | null
    ownerName: string | null
}

export function TodayChatVisibilityBanner({
    taskId,
    spaceId,
    ownerId,
    ownerName,
}: TodayChatVisibilityBannerProps): JSX.Element | null {
    const { spaces } = useValues(todaySpacesLogic)
    const { movedSessionSpaces } = useValues(todaySessionMenuLogic)
    const { user } = useValues(userLogic)
    const currentSpaceId = movedSessionSpaces[taskId] ?? spaceId
    const visibility = chatVisibility(currentSpaceId, spaces)
    const mine = ownerId !== null && ownerId === user?.id

    if (visibility === 'personal' || (mine && visibility === 'public')) {
        return null
    }
    const spaceName = spaces.find((space) => space.id === currentSpaceId)?.name
    const message =
        visibility === 'public'
            ? `${ownerName ?? 'A teammate'} started this public chat. You can read it, and pin it to keep it in your sidebar.`
            : `This chat is in ${spaceName ? `the older space ${spaceName}` : 'an older space'}. Only its members can see it.${mine ? ' Make it public or move it to personal to change who can see it.' : ''}`

    return (
        <Item
            variant="outline"
            tone="info"
            size="sm"
            className="mx-4 mt-3 w-auto"
            data-attr="today-chat-visibility-banner"
        >
            <ItemMedia variant="icon">{visibility === 'public' ? <IconGlobe /> : <IconPeople />}</ItemMedia>
            <ItemContent>
                <ItemDescription>{message}</ItemDescription>
            </ItemContent>
        </Item>
    )
}
