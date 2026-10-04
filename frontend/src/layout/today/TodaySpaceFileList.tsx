import { useValues } from 'kea'
import { ChangeEvent, useState } from 'react'

import { IconStar } from '@posthog/icons'
import { DropdownMenuRadioGroup, DropdownMenuRadioItem, Input, Text } from '@posthog/quill'

import { fileToSpaces, spaceLabel, todaySpacesLogic } from './todaySpacesLogic'

/** Desktop's "File to…" list gets a fixed height past this many spaces; the web adds its search there. */
const SPACE_SEARCH_THRESHOLD = 5

interface TodaySpaceFileListProps {
    /** Ticked and listed first. Null when the sessions being filed have no single space. */
    currentSpaceId: string | null
    onSelect: (spaceId: string) => void
    itemDataAttr: string
    searchDataAttr: string
}

/** The "File to…" menu body. The menu unmounts it on close, which also clears the search. */
export function TodaySpaceFileList({
    currentSpaceId,
    onSelect,
    itemDataAttr,
    searchDataAttr,
}: TodaySpaceFileListProps): JSX.Element {
    const { spaces } = useValues(todaySpacesLogic)
    const [search, setSearch] = useState('')
    const targets = fileToSpaces(spaces, currentSpaceId, search)

    return (
        <>
            {spaces.length > SPACE_SEARCH_THRESHOLD && (
                // Keep typing away from the menu's typeahead; Escape still closes the menu.
                <div className="p-1" onKeyDown={(event) => event.key !== 'Escape' && event.stopPropagation()}>
                    <Input
                        autoFocus
                        value={search}
                        onChange={(event: ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)}
                        placeholder="Search spaces…"
                        aria-label="Search spaces"
                        data-attr={searchDataAttr}
                    />
                </div>
            )}
            {targets.length === 0 && (
                <Text render={<div />} size="sm" variant="muted" className="px-2 py-1.5">
                    No spaces match your search
                </Text>
            )}
            <DropdownMenuRadioGroup value={currentSpaceId ?? ''} onValueChange={(value: string) => onSelect(value)}>
                {targets.map((space) => (
                    <DropdownMenuRadioItem key={space.id} value={space.id} closeOnClick data-attr={itemDataAttr}>
                        <span className="truncate">{spaceLabel(space)}</span>
                        {space.starred && space.system_role !== 'personal' && (
                            <IconStar className="ml-auto text-muted-foreground" />
                        )}
                    </DropdownMenuRadioItem>
                ))}
            </DropdownMenuRadioGroup>
        </>
    )
}
