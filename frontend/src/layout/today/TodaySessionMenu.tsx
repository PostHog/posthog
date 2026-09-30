import { useActions, useValues } from 'kea'

import { IconArchive, IconEllipsis, IconFolderMove, IconPencil, IconPin, IconPinFilled } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { todaySessionMenuLogic } from './todaySessionMenuLogic'
import { spaceLabel, todaySpacesLogic } from './todaySpacesLogic'

interface TodaySessionMenuProps {
    sessionId: string
    pinned: boolean
    spaceId: string | null
}

export function TodaySessionMenu({ sessionId, pinned, spaceId }: TodaySessionMenuProps): JSX.Element {
    const { sortedSpaces } = useValues(todaySpacesLogic)
    const { pendingSessionIds } = useValues(todaySessionMenuLogic)
    const { setSessionPinned, startRenaming, archiveSession, moveSession } = useActions(todaySessionMenuLogic)
    const saving = pendingSessionIds.includes(sessionId)
    const otherSpaces = sortedSpaces.filter((space) => space.id !== spaceId)

    return (
        <DropdownMenu>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <DropdownMenuTrigger
                            render={<Button size="icon-xs" aria-label="More" data-attr="today-session-menu" />}
                        />
                    }
                >
                    <IconEllipsis />
                </TooltipTrigger>
                <TooltipContent>More</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                    {saving && <DropdownMenuLabel>Saving your last change</DropdownMenuLabel>}
                    <DropdownMenuItem
                        disabled={saving}
                        onClick={() => setSessionPinned(sessionId, !pinned)}
                        data-attr="today-session-pin"
                    >
                        {pinned ? <IconPinFilled /> : <IconPin />}
                        <span>{pinned ? 'Unpin' : 'Pin'}</span>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        disabled={saving}
                        onClick={() => startRenaming(sessionId)}
                        data-attr="today-session-rename"
                    >
                        <IconPencil />
                        Rename
                    </DropdownMenuItem>
                    {otherSpaces.length > 0 && (
                        <DropdownMenuSub>
                            <DropdownMenuSubTrigger disabled={saving}>
                                <IconFolderMove />
                                Move to space
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                                {otherSpaces.map((space) => (
                                    <DropdownMenuItem
                                        key={space.id}
                                        disabled={saving}
                                        onClick={() => moveSession(sessionId, space.id)}
                                        data-attr="today-session-move"
                                    >
                                        {spaceLabel(space)}
                                    </DropdownMenuItem>
                                ))}
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    )}
                    <DropdownMenuItem
                        disabled={saving}
                        onClick={() => archiveSession(sessionId, true)}
                        data-attr="today-session-archive"
                    >
                        <IconArchive />
                        Archive
                    </DropdownMenuItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
