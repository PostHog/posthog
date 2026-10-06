import { useValues } from 'kea'

import { IconGlobe, IconPeople } from '@posthog/icons'
import { Text } from '@posthog/quill'

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
        <div
            className="mx-auto mt-3 flex w-full max-w-200 items-start gap-2 rounded-md border border-border bg-info px-3 py-2"
            data-attr="today-chat-visibility-banner"
        >
            <span className="mt-0.5 shrink-0 text-info-foreground">
                {visibility === 'public' ? <IconGlobe /> : <IconPeople />}
            </span>
            <Text size="sm">{message}</Text>
        </div>
    )
}
