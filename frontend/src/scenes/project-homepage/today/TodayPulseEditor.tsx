import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconSearch } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxSeparator,
    ComboboxTrigger,
    InputGroupAddon,
    Text,
} from '@posthog/quill'

import type { PulsePinApi, PulseSlotApi } from 'products/today/frontend/generated/api.schemas'

import { PULSE_TILES, pulsePinLimitReason, todayHighlightsLogic } from './todayHighlightsLogic'

interface EditorGroup {
    pinned: boolean
    items: string[]
}

function withoutKeys(rows: PulsePinApi[], keys: Set<string>): PulsePinApi[] {
    return rows.filter((row) => !keys.has(row.key))
}

function searchResults(search: string, listed: PulsePinApi[], insights: PulsePinApi[]): PulsePinApi[] {
    const query = search.trim().toLowerCase()
    const matches = listed.filter((row) => row.name.toLowerCase().includes(query))
    return [...matches, ...withoutKeys(insights, new Set(matches.map((row) => row.key)))]
}

function suggestionsOnHome(slots: PulseSlotApi[], pinnedKeys: Set<string>, suggestions: PulsePinApi[]): PulsePinApi[] {
    return slots
        .filter((slot) => !pinnedKeys.has(slot.key))
        .map((slot) => ({
            key: slot.key,
            name: slot.name,
            dashboard_id: suggestions.find((row) => row.key === slot.key)?.dashboard_id ?? null,
        }))
}

function editorNotes(
    searching: boolean,
    resultCount: number,
    loading: boolean,
    failed: boolean
): { searchNote: string | null; emptyNote: string } {
    if (!searching) {
        return { searchNote: null, emptyNote: 'No trend insights to pin yet' }
    }
    const emptyNote = 'No insights you can pin match your search'
    if (resultCount > 0 || !(loading || failed)) {
        return { searchNote: null, emptyNote }
    }
    return { searchNote: loading ? 'Searching…' : "Couldn't search your insights. Try again.", emptyNote }
}

function changedKey(before: Set<string>, after: Set<string>): string | undefined {
    return [...after].find((key) => !before.has(key)) ?? [...before].find((key) => !after.has(key))
}

export function TodayPulseEditor(): JSX.Element {
    const {
        pulsePins,
        pulseSlots,
        pulseSuggestions,
        pulseRecentInsights,
        pulseInsightResults,
        pulseInsightResultsLoading,
        pulseInsightSearchFailed,
        pulsePinsUnavailableReason,
    } = useValues(todayHighlightsLogic)
    const { togglePulsePin, loadPulseInsightResults, pulseEditorOpened } = useActions(todayHighlightsLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    const [pinnedOnOpen, setPinnedOnOpen] = useState<PulsePinApi[]>([])
    const [othersOnOpen, setOthersOnOpen] = useState<PulsePinApi[]>([])

    const searching = search.trim().length > 0
    const pinnedKeys = new Set(pulsePins.map((pin) => pin.key))
    const pinnedOnOpenKeys = new Set(pinnedOnOpen.map((pin) => pin.key))
    const others = [
        ...othersOnOpen,
        ...withoutKeys(pulseSuggestions, new Set([...pinnedOnOpenKeys, ...othersOnOpen.map((row) => row.key)])),
    ]
    const recent = withoutKeys(pulseRecentInsights, new Set([...pinnedOnOpenKeys, ...others.map((row) => row.key)]))
    const results = searchResults(
        search,
        [...pinnedOnOpen, ...others],
        pulseInsightResultsLoading || pulseInsightSearchFailed ? [] : pulseInsightResults
    )
    const rowByKey = new Map<string, PulsePinApi>(
        [...pulsePins, ...pinnedOnOpen, ...others, ...recent, ...results].map((row) => [row.key, row])
    )
    const groups: EditorGroup[] = (
        searching
            ? [{ pinned: false, items: results.map((row) => row.key) }]
            : [
                  { pinned: true, items: pinnedOnOpen.map((row) => row.key) },
                  { pinned: false, items: [...others, ...recent].map((row) => row.key) },
              ]
    ).filter((group) => group.items.length > 0)

    const { searchNote, emptyNote } = editorNotes(
        searching,
        results.length,
        pulseInsightResultsLoading,
        pulseInsightSearchFailed
    )

    return (
        <Combobox
            items={groups}
            multiple
            filter={null}
            value={[...pinnedKeys]}
            inputValue={search}
            open={open}
            highlightItemOnHover
            itemToStringLabel={(key: string) => rowByKey.get(key)?.name ?? ''}
            onInputValueChange={(value: string) => {
                setSearch(value)
                if (value.trim()) {
                    loadPulseInsightResults(value)
                }
            }}
            onOpenChange={(next: boolean) => {
                setOpen(next)
                if (next) {
                    pulseEditorOpened()
                    setPinnedOnOpen(pulsePins)
                    setOthersOnOpen(suggestionsOnHome(pulseSlots, pinnedKeys, pulseSuggestions))
                } else {
                    setSearch('')
                }
            }}
            onValueChange={(next: string[]) => {
                const row = rowByKey.get(changedKey(pinnedKeys, new Set(next)) ?? '')
                if (row) {
                    togglePulsePin(row, 'editor')
                }
            }}
        >
            <ComboboxTrigger
                ref={triggerRef}
                render={
                    <Button
                        variant="link-muted"
                        size="sm"
                        className="-mx-2 -my-1 text-[13px]"
                        aria-label="Edit numbers"
                        data-attr="today-pulse-edit"
                    >
                        Edit
                    </Button>
                }
            />
            <ComboboxContent
                anchor={triggerRef}
                align="end"
                className="w-72 [&_[data-slot=combobox-input-group-wrapper]]:border-b-0"
            >
                <ComboboxInput
                    placeholder="Search insights"
                    aria-label="Search insights"
                    autoFocus
                    showTrigger={false}
                    className="h-7"
                >
                    <InputGroupAddon align="inline-start">
                        <IconSearch className="size-3" />
                    </InputGroupAddon>
                </ComboboxInput>
                <ComboboxList>
                    {(group: EditorGroup) => (
                        <ComboboxGroup key={group.pinned ? 'pinned' : 'others'} items={group.items}>
                            {!group.pinned && groups.length > 1 ? <ComboboxSeparator /> : null}
                            <ComboboxCollection>
                                {(key: string) => {
                                    const row = rowByKey.get(key)
                                    const pinned = pinnedKeys.has(key)
                                    return (
                                        <ComboboxItem
                                            key={key}
                                            value={key}
                                            disabledReason={
                                                pulsePinsUnavailableReason ??
                                                pulsePinLimitReason(pulsePins.length, pinned)
                                            }
                                            data-attr="today-pulse-pin"
                                        >
                                            <span className="min-w-0 truncate">{row?.name}</span>
                                        </ComboboxItem>
                                    )
                                }}
                            </ComboboxCollection>
                        </ComboboxGroup>
                    )}
                </ComboboxList>
                {searchNote ? (
                    <Text size="xs" variant="muted" render={<p />} className="m-0 px-2.5 py-1.5">
                        {searchNote}
                    </Text>
                ) : (
                    <ComboboxEmpty>{emptyNote}</ComboboxEmpty>
                )}
                {pulsePins.length >= PULSE_TILES ? (
                    <Text size="xs" variant="muted" render={<p />} className="m-0 border-t px-2.5 py-1.5">
                        {PULSE_TILES} pinned. Unpin one to pin another.
                    </Text>
                ) : null}
            </ComboboxContent>
        </Combobox>
    )
}
