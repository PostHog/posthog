import { KeyboardEvent, PointerEvent } from 'react'

import type { LibraryEntry } from '../../editing/libraryCatalog'

/** One block in the library. Clicking adds it, and dragging places it anywhere on the canvas. */
export function CanvasBlocksLibraryItem({
    entry,
    onPointerDown,
    onActivate,
}: {
    entry: LibraryEntry
    onPointerDown: (event: PointerEvent, entry: LibraryEntry) => void
    onActivate: (entry: LibraryEntry) => void
}): JSX.Element {
    const Icon = entry.icon
    return (
        <button
            type="button"
            aria-label={`Add ${entry.label}`}
            data-attr={`canvas-blocks-library-${entry.type}`}
            onPointerDown={(event) => onPointerDown(event, entry)}
            onKeyDown={(event: KeyboardEvent) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onActivate(entry)
                }
            }}
            className="group/item flex w-full cursor-grab select-none items-center gap-2.5 rounded-md px-2 py-1.5 text-left outline-none transition-[background-color,scale] duration-150 ease-out hover:bg-fill-hover focus-visible:bg-fill-hover active:scale-[0.98] active:cursor-grabbing motion-reduce:transition-none motion-reduce:active:scale-100"
        >
            <div className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors duration-150 group-hover/item:text-foreground">
                <Icon className="size-4" />
            </div>
            <div className="min-w-0">
                <div className="truncate text-xs font-medium text-foreground">{entry.label}</div>
                <div className="line-clamp-2 text-xs leading-snug text-muted-foreground">{entry.description}</div>
            </div>
        </button>
    )
}
