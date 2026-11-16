import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { CommandKSearchFooter } from './CommandKSearchFooter'
import { COMMAND_K_LISTBOX_ID, CommandKSearchInput } from './CommandKSearchInput'
import { commandKSearchLogic } from './commandKSearchLogic'
import { rowDomId } from './CommandKSearchRow'
import { CommandKSearchSection } from './CommandKSearchSection'

export function CommandKSearchPalette(): JSX.Element {
    const { sections, highlightedRow } = useValues(commandKSearchLogic)
    const highlightedKey = highlightedRow?.key ?? null
    const scrollerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const row = highlightedKey ? document.getElementById(rowDomId(highlightedKey)) : null
        const scroller = scrollerRef.current
        if (!row || !scroller) {
            return
        }
        // scrollIntoView also scrolls the dialog, which clips the input, so scroll only the list.
        // quill-scroll-fade's scroll padding keeps the row clear of the sticky header and both fades.
        const style = getComputedStyle(scroller)
        const rowRect = row.getBoundingClientRect()
        const scrollerRect = scroller.getBoundingClientRect()
        const top = scrollerRect.top + parseFloat(style.scrollPaddingTop)
        const bottom = scrollerRect.bottom - parseFloat(style.scrollPaddingBottom)
        if (rowRect.top < top) {
            scroller.scrollTop -= top - rowRect.top
        } else if (rowRect.bottom > bottom) {
            scroller.scrollTop += rowRect.bottom - bottom
        }
    }, [highlightedKey])

    return (
        <div
            data-quill
            className="flex min-h-0 flex-1 flex-col bg-background text-foreground"
            data-attr="command-k-search"
        >
            <CommandKSearchInput />
            {/* The top fade starts below the 1.25rem sticky section header. quill-scroll-fade sets the
                scroll padding from it, which the effect above reads. */}
            <div
                ref={scrollerRef}
                className="quill-scroll-fade min-h-0 flex-1 overflow-y-auto border-t border-border bg-card [--quill-scroll-fade-top-offset:1.25rem] [scrollbar-gutter:stable]"
            >
                <div
                    id={COMMAND_K_LISTBOX_ID}
                    role="listbox"
                    aria-label="Search results"
                    // The colorful-product-icons group turns on each product's brand color, as in the navbar.
                    className="group/colorful-product-icons colorful-product-icons-true pb-2"
                >
                    {sections.map((section) => (
                        <CommandKSearchSection key={section.key} section={section} highlightedKey={highlightedKey} />
                    ))}
                </div>
            </div>
            <CommandKSearchFooter />
        </div>
    )
}
