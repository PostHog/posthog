import { ChangeEvent, PointerEvent, useMemo, useState } from 'react'

import { IconSearch, IconSparkles } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Text,
} from '@posthog/quill'

import { LIBRARY, LIBRARY_GROUPS, LibraryEntry } from '../../editing/libraryCatalog'
import { CanvasBlocksLibraryItem } from './CanvasBlocksLibraryItem'

const IMPROVE_PROMPT = 'Improve this canvas. Keep the blocks I placed, and make the layout clear and consistent.'

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
            <div className="flex flex-col gap-2 px-3 pt-3 pb-2">
                <InputGroup>
                    <InputGroupAddon align="inline-start">
                        <InputGroupText>
                            <IconSearch />
                        </InputGroupText>
                    </InputGroupAddon>
                    <InputGroupInput
                        type="search"
                        value={search}
                        placeholder="Search blocks"
                        aria-label="Search blocks"
                        onChange={(event: ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)}
                        data-attr="canvas-blocks-search"
                    />
                </InputGroup>
                <Text size="xs" variant="muted">
                    {addsAfter
                        ? `Click a block to add it after the selected ${addsAfter.toLowerCase()}, or drag it anywhere in the canvas.`
                        : 'Click a block to add it at the end, or drag it anywhere in the canvas.'}
                </Text>
            </div>
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-3 pb-4">
                {groups.length === 0 ? (
                    <Empty className="border-0 p-4">
                        <EmptyHeader>
                            <EmptyTitle>No blocks match your search</EmptyTitle>
                            <EmptyDescription>
                                Try another word, or ask the agent to build what you need.
                            </EmptyDescription>
                        </EmptyHeader>
                        <EmptyContent>
                            <Button variant="outline" size="sm" onClick={() => setSearch('')}>
                                Clear search
                            </Button>
                        </EmptyContent>
                    </Empty>
                ) : (
                    groups.map(({ group, entries }) => (
                        <section
                            key={group}
                            aria-labelledby={`canvas-blocks-group-${group}`}
                            className="flex flex-col gap-1"
                        >
                            <Text
                                id={`canvas-blocks-group-${group}`}
                                size="xs"
                                variant="muted"
                                weight="medium"
                                render={<h3 />}
                            >
                                {group}
                            </Text>
                            <div className="flex flex-col">
                                {entries.map((entry) => (
                                    <CanvasBlocksLibraryItem
                                        key={entry.type}
                                        entry={entry}
                                        onPointerDown={onPointerDown}
                                        onActivate={onActivate}
                                    />
                                ))}
                            </div>
                        </section>
                    ))
                )}
                <Item
                    variant="outline"
                    size="xs"
                    className="w-full items-start text-left hover:bg-fill-button-tertiary-hover"
                    render={
                        <button
                            type="button"
                            onClick={() => onAskAgent(IMPROVE_PROMPT)}
                            data-attr="canvas-blocks-ask-agent"
                        />
                    }
                >
                    <ItemMedia variant="icon" aria-hidden>
                        <IconSparkles />
                    </ItemMedia>
                    <ItemContent>
                        <ItemTitle>Ask the agent…</ItemTitle>
                        <ItemDescription>
                            Blocks are code in this canvas. The agent can change them, or build what no block covers.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            </div>
        </div>
    )
}
