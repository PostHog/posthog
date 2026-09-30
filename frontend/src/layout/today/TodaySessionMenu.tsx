import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    IconArchive,
    IconEllipsis,
    IconFolderMove,
    IconPencil,
    IconPin,
    IconPinFilled,
    IconSearch,
    IconSend,
} from '@posthog/icons'
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

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { TodaySessionHandoffDialog } from './TodaySessionHandoffDialog'
import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { spaceLabel, todaySpacesLogic } from './todaySpacesLogic'

interface TodaySessionMenuProps {
    sessionId: string
    pinned: boolean
    spaceId: string | null
    surface: TodaySessionSurface
    canHandOff?: boolean
    analysisRunId?: string | null
}

export function TodaySessionMenu({
    sessionId,
    pinned,
    spaceId,
    surface,
    canHandOff = false,
    analysisRunId = null,
}: TodaySessionMenuProps): JSX.Element {
    const menuId = useId()
    const { featureFlags } = useValues(featureFlagLogic)
    const { sortedSpaces } = useValues(todaySpacesLogic)
    const { pendingSessionIds, handoffMenuId } = useValues(todaySessionMenuLogic)
    const { setSessionPinned, startRenaming, archiveSession, moveSession, openHandoff, analyzeSession } =
        useActions(todaySessionMenuLogic)
    const runId = featureFlags[FEATURE_FLAGS.POSTHOG_CODE_TASK_ANALYSIS] ? analysisRunId : null
    const saving = pendingSessionIds.includes(sessionId)
    const otherSpaces = sortedSpaces.filter((space) => space.id !== spaceId)
    const label = saving ? 'Saving your last change' : 'More actions'

    return (
        <>
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
                    <DropdownMenuItem
                        onClick={() => setSessionPinned(sessionId, !pinned)}
                        data-attr="today-session-pin"
                    >
                        {pinned ? <IconPinFilled /> : <IconPin />}
                        {pinned ? 'Unpin' : 'Pin'}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        onClick={() => startRenaming(sessionId, surface)}
                        data-attr="today-session-rename"
                    >
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
                    {runId && (
                        <DropdownMenuItem
                            onClick={() => analyzeSession(sessionId, runId)}
                            data-attr="today-session-analyze"
                        >
                            <IconSearch />
                            Run analysis
                        </DropdownMenuItem>
                    )}
                    {canHandOff && (
                        <DropdownMenuItem onClick={() => openHandoff(menuId)} data-attr="today-session-handoff">
                            <IconSend />
                            Hand off…
                        </DropdownMenuItem>
                    )}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={() => archiveSession(sessionId, true)} data-attr="today-session-archive">
                        <IconArchive />
                        Archive
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            {canHandOff && handoffMenuId === menuId && <TodaySessionHandoffDialog sessionId={sessionId} />}
        </>
    )
}
