import { useMountedLogic, useValues } from 'kea'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from 'react'

import { IconBolt } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { createFuse } from 'lib/utils/fuseSearch'
import { isKeyOf } from 'lib/utils/guards'

import type { MacroApi } from '../../generated/api.schemas'
import { macrosLogic } from './macrosLogic'

export type MacroPickerRef = {
    onKeyDown: (event: KeyboardEvent) => boolean
}

export interface MacroPickerProps {
    /** Called with the chosen macro. */
    onSelect: (macro: MacroApi) => void
    /** Externally controlled query (slash-command flow reads it from the typed text). */
    query?: string
    /** Show an inline search box (toolbar flow); omit when the query is controlled externally. */
    showSearchInput?: boolean
}

/**
 * Renders the searchable list of macros with keyboard navigation. Shared by the `/` slash-command
 * popup (query controlled by the editor) and the toolbar button (its own search box).
 */
export const MacroPicker = forwardRef<MacroPickerRef, MacroPickerProps>(function MacroPicker(
    { onSelect, query: controlledQuery, showSearchInput = false },
    ref
): JSX.Element {
    const { teamMacros, personalMacros, macrosLoading, loadFailed } = useValues(macrosLogic)
    const [internalQuery, setInternalQuery] = useState('')
    const query = (controlledQuery ?? internalQuery).trim()
    const [selectedIndex, setSelectedIndex] = useState(0)

    const allMacros = useMemo(() => [...teamMacros, ...personalMacros], [teamMacros, personalMacros])

    const fuse = useMemo(() => createFuse(allMacros, { keys: ['name', 'description'] }), [allMacros])

    const filteredMacros = useMemo(() => {
        if (!query) {
            return allMacros
        }
        return fuse.search(query).map((result) => result.item)
    }, [query, fuse, allMacros])

    useEffect(() => {
        setSelectedIndex(0)
    }, [query])

    const execute = useCallback(
        (macro: MacroApi | undefined): void => {
            if (macro) {
                onSelect(macro)
            }
        },
        [onSelect]
    )

    const onKeyDown = useCallback(
        (event: KeyboardEvent): boolean => {
            const count = filteredMacros.length
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
                    // Require a typed query before Enter selects, so a bare `/` + Enter is treated
                    // as a normal newline rather than silently inserting a macro (and firing its
                    // ticket actions). Explicit clicks still work with no query.
                    const macro = query ? filteredMacros[selectedIndex] : undefined
                    if (!macro) {
                        return false
                    }
                    execute(macro)
                    return true
                },
            }
            if (isKeyOf(event.key, keyMappings)) {
                return keyMappings[event.key]()
            }
            return false
        },
        [filteredMacros, selectedIndex, execute, query]
    )

    useImperativeHandle(ref, () => ({ onKeyDown }), [onKeyDown])

    return (
        <div className="flex flex-col gap-1 min-w-[20rem] max-w-[25rem]">
            {showSearchInput && (
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search macros..."
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
                {filteredMacros.map((macro, index) => (
                    <LemonButton
                        key={macro.short_id}
                        fullWidth
                        icon={<IconBolt />}
                        active={index === selectedIndex}
                        onClick={() => execute(macro)}
                        tooltip={macro.description || undefined}
                    >
                        <div className="flex flex-col items-start">
                            <span>{macro.name}</span>
                            {macro.description ? (
                                <span className="text-xs text-secondary truncate max-w-full">{macro.description}</span>
                            ) : null}
                        </div>
                    </LemonButton>
                ))}
                {filteredMacros.length === 0 && (
                    <div className="text-secondary p-2 text-center">
                        {macrosLoading
                            ? 'Loading macros...'
                            : loadFailed
                              ? "Couldn't load macros. Try again."
                              : query
                                ? 'No matching macros'
                                : 'No macros yet'}
                    </div>
                )}
            </div>
        </div>
    )
})

/**
 * Keeps `macrosLogic` mounted for the lifetime of its parent so the macro list is fetched once,
 * not re-fetched every time the slash-command popup or toolbar picker opens and closes.
 */
export function MacrosKeepAlive(): null {
    useMountedLogic(macrosLogic)
    return null
}
