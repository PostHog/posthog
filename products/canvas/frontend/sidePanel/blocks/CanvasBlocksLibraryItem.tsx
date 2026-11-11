import { KeyboardEvent, PointerEvent } from 'react'

import { Item, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

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
        <Item
            size="xs"
            // The app compiles fill tokens as plain classes only, so hover uses the tertiary button fill.
            className="w-full cursor-grab items-start text-left select-none hover:bg-fill-button-tertiary-hover focus-visible:bg-fill-button-tertiary-hover active:cursor-grabbing"
            render={
                <button
                    type="button"
                    aria-label={`Add ${entry.label}`}
                    data-attr={`canvas-blocks-library-${entry.type}`}
                    onClick={(event) => {
                        if (event.detail === 0) {
                            onActivate(entry)
                        }
                    }}
                    onPointerDown={(event) => onPointerDown(event, entry)}
                    onKeyDown={(event: KeyboardEvent) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault()
                            onActivate(entry)
                        }
                    }}
                />
            }
        >
            <ItemMedia variant="icon" aria-hidden>
                <Icon />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle className="truncate">{entry.label}</ItemTitle>
                <ItemDescription className="line-clamp-2">{entry.description}</ItemDescription>
            </ItemContent>
        </Item>
    )
}
