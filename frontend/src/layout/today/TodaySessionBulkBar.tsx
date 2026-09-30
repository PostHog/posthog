import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArchive, IconFolder, IconPin, IconPinFilled, IconStar, IconX } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { todaySessionMenuLogic } from './todaySessionMenuLogic'
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { fileToSpaces, spaceLabel, todaySpacesLogic } from './todaySpacesLogic'

export function TodaySessionBulkBar(): JSX.Element | null {
    const { visibleSelectedIds, batchInProgress } = useValues(todaySessionSelectionLogic)
    const { clearSelection } = useActions(todaySessionSelectionLogic)
    const { spaces, pinnedItems } = useValues(todaySpacesLogic)
    const { bulkSetSessionsPinned, bulkMoveSessions, bulkArchiveSessions } = useActions(todaySessionMenuLogic)
    const [moveMenuOpen, setMoveMenuOpen] = useState(false)
    const hasSelection = visibleSelectedIds.length > 0

    useEffect(() => {
        if (!hasSelection || moveMenuOpen) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            // Escape in a field, such as the rename input, belongs to that field.
            const inField = event.target instanceof HTMLElement && event.target.closest('input, textarea')
            if (event.key === 'Escape' && !event.defaultPrevented && !inField) {
                clearSelection()
            }
        }
        document.addEventListener('keydown', onKeyDown)
        return () => document.removeEventListener('keydown', onKeyDown)
    }, [hasSelection, moveMenuOpen, clearSelection])

    if (!hasSelection) {
        return null
    }

    const pinnedIds = new Set(pinnedItems.map((item) => item.id))
    const allPinned = visibleSelectedIds.every((id) => pinnedIds.has(id))
    const disabledTitle = batchInProgress ? 'Saving your last change' : undefined

    return (
        <div
            role="toolbar"
            aria-label="Selected sessions"
            className="mb-2 flex flex-col gap-1.5 rounded-md border border-border bg-background p-1.5 shadow-sm"
            data-attr="today-session-bulk-bar"
        >
            <div className="flex min-w-0 items-center gap-1">
                <Text size="xs" weight="medium" className="min-w-0 flex-1 truncate px-1" aria-live="polite">
                    {pluralize(visibleSelectedIds.length, 'session')} selected
                </Text>
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon-xs"
                                aria-label="Clear selection"
                                onClick={clearSelection}
                                data-attr="today-session-bulk-clear"
                            />
                        }
                    >
                        <IconX />
                    </TooltipTrigger>
                    <TooltipContent>Clear selection (Esc)</TooltipContent>
                </Tooltip>
            </div>
            <div className="flex flex-wrap gap-1">
                <Button
                    variant="outline"
                    size="sm"
                    disabled={batchInProgress}
                    title={disabledTitle}
                    onClick={() => bulkSetSessionsPinned(visibleSelectedIds, !allPinned)}
                    data-attr="today-session-bulk-pin"
                >
                    {allPinned ? <IconPinFilled /> : <IconPin />}
                    {allPinned ? 'Unpin' : 'Pin'}
                </Button>
                {spaces.length > 0 && (
                    <DropdownMenu open={moveMenuOpen} onOpenChange={setMoveMenuOpen}>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    variant="outline"
                                    size="sm"
                                    disabled={batchInProgress}
                                    title={disabledTitle}
                                    data-attr="today-session-bulk-move-open"
                                />
                            }
                        >
                            <IconFolder />
                            Move to…
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" className="max-h-80 w-64">
                            {fileToSpaces(spaces, null).map((space) => (
                                <DropdownMenuItem
                                    key={space.id}
                                    onClick={() => bulkMoveSessions(visibleSelectedIds, space.id)}
                                    data-attr="today-session-bulk-move"
                                >
                                    <span className="truncate">{spaceLabel(space)}</span>
                                    {space.starred && space.system_role !== 'personal' && (
                                        <IconStar className="ml-auto text-muted-foreground" />
                                    )}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
                <Button
                    variant="outline"
                    size="sm"
                    disabled={batchInProgress}
                    title={disabledTitle}
                    onClick={() => bulkArchiveSessions(visibleSelectedIds, true)}
                    data-attr="today-session-bulk-archive"
                >
                    <IconArchive />
                    Archive
                </Button>
            </div>
        </div>
    )
}
