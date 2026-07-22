import { useMountedLogic, useValues } from 'kea'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from 'react'

import { IconShortcut } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { createFuse } from 'lib/utils/fuseSearch'
import { isKeyOf } from 'lib/utils/guards'

import type { QuickActionApi } from '../../generated/api.schemas'
import { quickActionsLogic } from './quickActionsLogic'

export type QuickActionPickerRef = {
    onKeyDown: (event: KeyboardEvent) => boolean
}

export interface QuickActionPickerProps {
    /** Called with the chosen quick action. */
    onSelect: (quickAction: QuickActionApi) => void
    /** Externally controlled query (slash-command flow reads it from the typed text). */
    query?: string
    /** Show an inline search box (toolbar flow); omit when the query is controlled externally. */
    showSearchInput?: boolean
}

/**
 * Renders the searchable list of quick actions with keyboard navigation. Shared by the `/`
 * slash-command popup (query controlled by the editor) and the toolbar button (its own search box).
 */
export const QuickActionPicker = forwardRef<QuickActionPickerRef, QuickActionPickerProps>(function QuickActionPicker(
    { onSelect, query: controlledQuery, showSearchInput = false },
    ref
): JSX.Element {
    const { teamQuickActions, personalQuickActions, quickActionsLoading, loadFailed } = useValues(quickActionsLogic)
    const [internalQuery, setInternalQuery] = useState('')
    const query = (controlledQuery ?? internalQuery).trim()
    const [selectedIndex, setSelectedIndex] = useState(0)

    const all = useMemo(() => [...teamQuickActions, ...personalQuickActions], [teamQuickActions, personalQuickActions])

    const fuse = useMemo(() => createFuse(all, { keys: ['name', 'description'] }), [all])

    const filtered = useMemo(() => {
        if (!query) {
            return all
        }
        return fuse.search(query).map((result) => result.item)
    }, [query, fuse, all])

    useEffect(() => {
        setSelectedIndex(0)
    }, [query])

    const execute = useCallback(
        (quickAction: QuickActionApi | undefined): void => {
            if (quickAction) {
                onSelect(quickAction)
            }
        },
        [onSelect]
    )

    const onKeyDown = useCallback(
        (event: KeyboardEvent): boolean => {
            const count = filtered.length
            const keyMappings = {
                ArrowUp: (): boolean => {
                    if (count > 0) {
                        setSelectedIndex((i) => (i - 1 + count) % count)
                    }
                    return true
                },
                ArrowDown: (): boolean => {
                    if (count > 0) {
                        setSelectedIndex((i) => (i + 1) % count)
                    }
                    return true
                },
                Enter: (): boolean => {
                    // Require a typed query before Enter selects, so a bare `/` + Enter is treated as
                    // a normal newline rather than silently running a quick action. Clicks still work.
                    const quickAction = query ? filtered[selectedIndex] : undefined
                    if (!quickAction) {
                        return false
                    }
                    execute(quickAction)
                    return true
                },
            }
            if (isKeyOf(event.key, keyMappings)) {
                return keyMappings[event.key]()
            }
            return false
        },
        [filtered, selectedIndex, execute, query]
    )

    useImperativeHandle(ref, () => ({ onKeyDown }), [onKeyDown])

    return (
        <div className="flex flex-col gap-1 min-w-[20rem] max-w-[25rem]">
            {showSearchInput && (
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search quick actions..."
                    value={internalQuery}
                    onChange={setInternalQuery}
                    onKeyDown={(e) => {
                        if (onKeyDown(e.nativeEvent)) {
                            e.preventDefault()
                        }
                    }}
                    autoFocus
                />
            )}
            <div className="deprecated-space-y-px overflow-y-auto max-h-[20rem]">
                {filtered.map((quickAction, index) => (
                    <LemonButton
                        key={quickAction.short_id}
                        fullWidth
                        icon={<IconShortcut />}
                        active={index === selectedIndex}
                        onClick={() => execute(quickAction)}
                        tooltip={quickAction.description || undefined}
                        sideIcon={quickAction.workflow_id ? <LemonTag type="completion">Workflow</LemonTag> : undefined}
                    >
                        <div className="flex flex-col items-start">
                            <span>{quickAction.name}</span>
                            {quickAction.description ? (
                                <span className="text-xs text-secondary truncate max-w-full">
                                    {quickAction.description}
                                </span>
                            ) : null}
                        </div>
                    </LemonButton>
                ))}
                {filtered.length === 0 && (
                    <div className="text-secondary p-2 text-center">
                        {quickActionsLoading
                            ? 'Loading quick actions...'
                            : loadFailed
                              ? "Couldn't load quick actions. Try again."
                              : query
                                ? 'No matching quick actions'
                                : 'No quick actions yet'}
                    </div>
                )}
            </div>
        </div>
    )
})

/**
 * Keeps `quickActionsLogic` mounted for the lifetime of its parent so the list is fetched once,
 * not re-fetched every time the slash-command popup or toolbar picker opens and closes.
 */
export function QuickActionsKeepAlive(): null {
    useMountedLogic(quickActionsLogic)
    return null
}
