import { useActions, useValues } from 'kea'
import { ChangeEvent, useId, useState } from 'react'

import {
    IconArchive,
    IconCopy,
    IconEllipsis,
    IconExternal,
    IconFolder,
    IconPencil,
    IconPin,
    IconPinFilled,
    IconSearch,
    IconSend,
    IconStar,
    IconStopFilled,
} from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    Input,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { TodaySessionArchiveDialog } from './TodaySessionArchiveDialog'
import { TodaySessionHandoffDialog } from './TodaySessionHandoffDialog'
import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { fileToSpaces, spaceLabel, todaySpacesLogic } from './todaySpacesLogic'

/** Desktop's "File to…" list gets a fixed height past this many spaces; the web adds its search there. */
const SPACE_SEARCH_THRESHOLD = 5

interface TodaySessionMenuProps {
    sessionId: string
    title: string
    pinned: boolean
    spaceId: string | null
    surface: TodaySessionSurface
    canHandOff?: boolean
    analysisRunId?: string | null
    /** The latest run while it is an active cloud run: it can be stopped, and archiving asks first. */
    activeRunId?: string | null
}

export function TodaySessionMenu({
    sessionId,
    title,
    pinned,
    spaceId,
    surface,
    canHandOff = false,
    analysisRunId = null,
    activeRunId = null,
}: TodaySessionMenuProps): JSX.Element {
    const menuId = useId()
    const { featureFlags } = useValues(featureFlagLogic)
    const { spaces } = useValues(todaySpacesLogic)
    const { pendingSessionIds, handoffMenuId, archiveConfirmMenuId } = useValues(todaySessionMenuLogic)
    const {
        setSessionPinned,
        startRenaming,
        requestArchive,
        moveSession,
        openHandoff,
        analyzeSession,
        openSessionInNewTab,
        copySessionLink,
        stopSession,
    } = useActions(todaySessionMenuLogic)
    const [spaceSearch, setSpaceSearch] = useState('')
    const runId = featureFlags[FEATURE_FLAGS.POSTHOG_CODE_TASK_ANALYSIS] ? analysisRunId : null
    const saving = pendingSessionIds.includes(sessionId)
    const fileTargets = fileToSpaces(spaces, spaceId, spaceSearch)
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
                <DropdownMenuContent align="end" className="w-56">
                    <DropdownMenuItem
                        onClick={() => openSessionInNewTab(sessionId)}
                        data-attr="today-session-open-new-tab"
                    >
                        <IconExternal />
                        Open in new tab
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => copySessionLink(sessionId)} data-attr="today-session-copy-link">
                        <IconCopy />
                        Copy link
                    </DropdownMenuItem>
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
                    {runId && (
                        <DropdownMenuItem
                            onClick={() => analyzeSession(sessionId, runId)}
                            data-attr="today-session-analyze"
                        >
                            <IconSearch />
                            Run analysis
                        </DropdownMenuItem>
                    )}
                    {activeRunId && (
                        <DropdownMenuItem
                            onClick={() => stopSession(sessionId, activeRunId)}
                            data-attr="today-session-stop"
                        >
                            <IconStopFilled />
                            Stop session
                        </DropdownMenuItem>
                    )}
                    {spaces.length > 0 && (
                        <DropdownMenuSub onOpenChange={(open: boolean) => !open && setSpaceSearch('')}>
                            <DropdownMenuSubTrigger>
                                <IconFolder />
                                File to…
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent className="max-h-80 w-64">
                                {spaces.length > SPACE_SEARCH_THRESHOLD && (
                                    // Keep typing away from the menu's typeahead; Escape still closes the menu.
                                    <div
                                        className="p-1"
                                        onKeyDown={(event) => event.key !== 'Escape' && event.stopPropagation()}
                                    >
                                        <Input
                                            autoFocus
                                            value={spaceSearch}
                                            onChange={(event: ChangeEvent<HTMLInputElement>) =>
                                                setSpaceSearch(event.target.value)
                                            }
                                            placeholder="Search spaces…"
                                            aria-label="Search spaces"
                                            data-attr="today-session-move-search"
                                        />
                                    </div>
                                )}
                                {fileTargets.length === 0 && (
                                    <Text render={<div />} size="sm" variant="muted" className="px-2 py-1.5">
                                        No spaces match your search
                                    </Text>
                                )}
                                <DropdownMenuRadioGroup
                                    value={spaceId ?? ''}
                                    onValueChange={(value: string) => moveSession(sessionId, value)}
                                >
                                    {fileTargets.map((space) => (
                                        <DropdownMenuRadioItem
                                            key={space.id}
                                            value={space.id}
                                            closeOnClick
                                            data-attr="today-session-move"
                                        >
                                            <span className="truncate">{spaceLabel(space)}</span>
                                            {space.starred && space.system_role !== 'personal' && (
                                                <IconStar className="ml-auto text-muted-foreground" />
                                            )}
                                        </DropdownMenuRadioItem>
                                    ))}
                                </DropdownMenuRadioGroup>
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    )}
                    {canHandOff && (
                        <DropdownMenuItem onClick={() => openHandoff(menuId)} data-attr="today-session-handoff">
                            <IconSend />
                            Hand off…
                        </DropdownMenuItem>
                    )}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                        onClick={() => requestArchive(sessionId, menuId, activeRunId)}
                        data-attr="today-session-archive"
                    >
                        <IconArchive />
                        Archive
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            {canHandOff && handoffMenuId === menuId && <TodaySessionHandoffDialog sessionId={sessionId} />}
            {activeRunId && archiveConfirmMenuId === menuId && (
                <TodaySessionArchiveDialog sessionId={sessionId} title={title} runId={activeRunId} />
            )}
        </>
    )
}
