import './sidebar.scss'

import { type ReactNode, useRef } from 'react'

import { Autocomplete, AutocompleteClear, AutocompleteInput, AutocompleteList, cn } from '@posthog/quill'

import { highlightOption, toggleSectionWithArrow } from './sidebarTreeKeys'

export interface SidebarSearchListProps {
    query: string
    onQueryChange: (query: string) => void
    /** The field's accessible name. Its placeholder adds an ellipsis, for example "Search tools…". */
    searchLabel: string
    dataAttr: string
    searchActions?: ReactNode
    header?: ReactNode
    children: ReactNode
    className?: string
    /** For a pane whose own sections scroll, so the list itself does not. */
    listClassName?: string
}

/**
 * A sidebar pane's search field and list, after Desktop's sidebar. The list stays open, the field filters it,
 * the arrow keys move between rows and Enter opens the highlighted row. With the field empty, Right and Left open and
 * close a highlighted section heading, and Left on a row closes its section, like a tree.
 */
export function SidebarSearchList({
    query,
    onQueryChange,
    searchLabel,
    dataAttr,
    searchActions,
    header,
    children,
    className,
    listClassName,
}: SidebarSearchListProps): JSX.Element {
    const listRef = useRef<HTMLDivElement>(null)
    return (
        <Autocomplete<string>
            inline
            open
            value={query}
            // No `items`: each row registers itself in render order, so the arrow keys walk exactly what shows.
            // The panes filter their own rows.
            filter={null}
            onValueChange={(value: string, details: { reason: string }) => {
                if (details.reason === 'input-change') {
                    onQueryChange(value)
                }
            }}
        >
            <div className={cn('flex min-h-0 flex-1 flex-col', className)}>
                <div className="flex shrink-0 items-center gap-1 [&_[data-slot=autocomplete-input-group-wrapper]]:min-w-0 [&_[data-slot=autocomplete-input-group-wrapper]]:flex-1 [&_[data-slot=autocomplete-popover-separator]]:hidden">
                    <AutocompleteInput
                        placeholder={`${searchLabel}…`}
                        aria-label={searchLabel}
                        data-attr={dataAttr}
                        className="h-7"
                        onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                            if (event.key === 'Escape' && query !== '') {
                                event.preventDefault()
                                event.stopPropagation()
                                onQueryChange('')
                            } else if (query === '') {
                                const heading = toggleSectionWithArrow(
                                    listRef.current?.querySelector('[data-highlighted]'),
                                    event.key
                                )
                                if (heading) {
                                    event.preventDefault()
                                    // The section's rows unmount, so the highlight goes back to its heading.
                                    requestAnimationFrame(() => highlightOption(heading))
                                }
                            }
                        }}
                    >
                        {query !== '' && (
                            <AutocompleteClear
                                aria-label="Clear search"
                                data-attr={`${dataAttr}-clear`}
                                onClick={() => onQueryChange('')}
                            />
                        )}
                    </AutocompleteInput>
                    {searchActions}
                </div>
                {header && <div className="mt-2 shrink-0">{header}</div>}
                <AutocompleteList
                    ref={listRef}
                    className={cn(
                        'SidebarSearchList mt-2 min-h-0 !max-h-none flex-1 overflow-y-auto !p-0 pb-6',
                        header && 'mt-1',
                        listClassName
                    )}
                >
                    {children}
                </AutocompleteList>
            </div>
        </Autocomplete>
    )
}
