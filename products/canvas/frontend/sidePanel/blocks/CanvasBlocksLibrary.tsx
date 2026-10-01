import { ChangeEvent, PointerEvent, useMemo, useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { Input } from '@posthog/quill'

import { LIBRARY, LIBRARY_GROUPS, LibraryEntry } from '../../editing/libraryCatalog'
import { CanvasBlocksLibraryItem } from './CanvasBlocksLibraryItem'

/** The block library: every block by group, searchable, with a way to hand the rest to the agent. */
export function CanvasBlocksLibrary({
    addsAfter,
    onPointerDown,
    onActivate,
    onAskAgent,
}: {
    addsAfter: string | null
    onPointerDown: (event: PointerEvent, entry: LibraryEntry) => void
    onActivate: (entry: LibraryEntry) => void
    onAskAgent: (message: string) => void
}): JSX.Element {
    const [search, setSearch] = useState('')
    const groups = useMemo(() => {
        const needle = search.trim().toLowerCase()
        const matches = (entry: LibraryEntry): boolean =>
            !needle || entry.label.toLowerCase().includes(needle) || entry.description.toLowerCase().includes(needle)
        return LIBRARY_GROUPS.flatMap((group) => {
            const entries = LIBRARY.filter((entry) => entry.group === group && matches(entry))
            return entries.length > 0 ? [{ group, entries }] : []
        })
    }, [search])
    return (
        <div className="flex min-h-0 flex-1 flex-col">
            <div className="px-3 pt-3 pb-2">
                <Input
                    value={search}
                    placeholder="Search blocks"
                    aria-label="Search blocks"
                    onChange={(event: ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)}
                    data-attr="canvas-blocks-search"
                />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-4">
                {groups.map(({ group, entries }) => (
                    <div key={group} className="mt-2">
                        <div className="px-2 pb-1 text-xs font-medium text-muted-foreground">{group}</div>
                        {entries.map((entry) => (
                            <CanvasBlocksLibraryItem
                                key={entry.type}
                                entry={entry}
                                onPointerDown={onPointerDown}
                                onActivate={onActivate}
                            />
                        ))}
                    </div>
                ))}
                {groups.length === 0 ? (
                    <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                        No blocks match “{search}”
                    </div>
                ) : null}
                <div className="mx-2 mt-4 rounded-md bg-fill-hover px-2.5 py-2 text-xs leading-snug text-muted-foreground">
                    {addsAfter
                        ? `Click a block to add it after the selected ${addsAfter.toLowerCase()}, or drag it anywhere in the canvas.`
                        : 'Click a block to add it at the end, or drag it anywhere in the canvas.'}
                </div>
                <div className="mt-4 px-2">
                    <button
                        type="button"
                        onClick={() =>
                            onAskAgent(
                                'Improve this canvas. Keep the blocks I placed, and make the layout clear and consistent.'
                            )
                        }
                        className="flex w-full items-start gap-2.5 rounded-md border border-dashed border-border px-2.5 py-2 text-left transition-colors hover:bg-fill-hover"
                        data-attr="canvas-blocks-ask-agent"
                    >
                        <IconSparkles className="mt-px shrink-0" />
                        <span className="min-w-0">
                            <span className="block text-xs font-medium text-foreground">Ask the agent</span>
                            <span className="block text-xs leading-snug text-muted-foreground">
                                Blocks are code in this canvas. The agent can change them, or build what no block
                                covers.
                            </span>
                        </span>
                    </button>
                </div>
            </div>
        </div>
    )
}
