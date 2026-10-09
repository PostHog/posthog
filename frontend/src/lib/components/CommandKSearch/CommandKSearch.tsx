import { useValues } from 'kea'
import { useEffect } from 'react'

import { ScrollArea } from '@posthog/quill'

import { CommandKSearchFooter } from './CommandKSearchFooter'
import { COMMAND_K_LISTBOX_ID, CommandKSearchInput } from './CommandKSearchInput'
import { commandKSearchLogic } from './commandKSearchLogic'
import { CommandKSearchNoResults } from './CommandKSearchNoResults'
import { rowDomId } from './CommandKSearchRow'
import { CommandKSearchSection } from './CommandKSearchSection'

/** Command K search with smart filters. The UX contract lives in COMMAND_K_SEARCH_UX.md next to this file. */
export function CommandKSearch(): JSX.Element {
    const { sections, highlightedRow, showNoResults } = useValues(commandKSearchLogic)
    const highlightedKey = highlightedRow?.key ?? null

    useEffect(() => {
        const row = highlightedKey ? document.getElementById(rowDomId(highlightedKey)) : null
        const viewport = row?.closest<HTMLElement>('[data-slot="scroll-area-viewport"]')
        if (!row || !viewport) {
            return
        }
        // scrollIntoView also scrolls the dialog, which clips the input, so scroll only the list.
        // The sticky section header covers the top of the viewport, so keep rows below it.
        const header = row.closest('[role="group"]')?.querySelector<HTMLElement>('[data-slot="menu-label"]')
        const headerHeight = header?.offsetHeight ?? 0
        const rowRect = row.getBoundingClientRect()
        const viewportRect = viewport.getBoundingClientRect()
        if (rowRect.top < viewportRect.top + headerHeight) {
            viewport.scrollTop -= viewportRect.top + headerHeight - rowRect.top
        } else if (rowRect.bottom > viewportRect.bottom) {
            viewport.scrollTop += rowRect.bottom - viewportRect.bottom
        }
    }, [highlightedKey])

    return (
        <div
            data-quill
            className="flex min-h-0 flex-1 flex-col bg-background text-foreground"
            data-attr="command-k-search"
        >
            <CommandKSearchInput />
            <ScrollArea
                // Sticky section headers sit at z-10, so lift the scrollbar above them.
                className="flex min-h-0 flex-1 flex-col border-t border-border [&>[data-slot=scroll-area-scrollbar]]:z-20"
                viewportClassName="h-auto min-h-0 flex-1"
            >
                <div
                    id={COMMAND_K_LISTBOX_ID}
                    role="listbox"
                    aria-label="Search results"
                    // The colorful-product-icons group turns on each product's brand color, as in the navbar.
                    className="group/colorful-product-icons colorful-product-icons-true bg-card pb-1"
                >
                    {sections.map((section) => (
                        <CommandKSearchSection key={section.key} section={section} highlightedKey={highlightedKey} />
                    ))}
                </div>
                {showNoResults && <CommandKSearchNoResults />}
            </ScrollArea>
            <CommandKSearchFooter />
        </div>
    )
}
