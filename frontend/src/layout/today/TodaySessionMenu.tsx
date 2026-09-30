import { useActions, useValues } from 'kea'

import { IconArchive, IconEllipsis, IconFolderMove, IconPencil, IconPin, IconPinFilled } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { spaceLabel, todaySpacesLogic } from './todaySpacesLogic'

interface TodaySessionMenuProps {
    sessionId: string
    pinned: boolean
    spaceId: string | null
    surface: TodaySessionSurface
}

export function TodaySessionMenu({ sessionId, pinned, spaceId, surface }: TodaySessionMenuProps): JSX.Element {
    const { sortedSpaces } = useValues(todaySpacesLogic)
    const { pendingSessionIds } = useValues(todaySessionMenuLogic)
    const { setSessionPinned, startRenaming, archiveSession, moveSession } = useActions(todaySessionMenuLogic)
    const saving = pendingSessionIds.includes(sessionId)
    const otherSpaces = sortedSpaces.filter((space) => space.id !== spaceId)
    const label = saving ? 'Saving your last change' : 'More actions'

    return (
        <DropdownMenu>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon-xs"
                                    aria-label={label}
                                    loading={saving}
                                    data-attr="today-session-menu"
                                />
                            }
                        />
                    }
                >
                    <IconEllipsis />
                </TooltipTrigger>
                <TooltipContent>{label}</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuItem onClick={() => setSessionPinned(sessionId, !pinned)} data-attr="today-session-pin">
                    {pinned ? <IconPinFilled /> : <IconPin />}
                    {pinned ? 'Unpin' : 'Pin'}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => startRenaming(sessionId, surface)} data-attr="today-session-rename">
                    <IconPencil />
                    Rename
                </DropdownMenuItem>
                {otherSpaces.length > 0 && (
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger>
                            <IconFolderMove />
                            Move to space
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            {otherSpaces.map((space) => (
                                <DropdownMenuItem
                                    key={space.id}
                                    onClick={() => moveSession(sessionId, space.id)}
                                    data-attr="today-session-move"
                                >
                                    {spaceLabel(space)}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => archiveSession(sessionId, true)} data-attr="today-session-archive">
                    <IconArchive />
                    Archive
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
