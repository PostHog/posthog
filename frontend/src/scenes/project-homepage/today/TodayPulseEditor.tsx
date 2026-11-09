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

import type { PulsePinApi } from 'products/today/frontend/generated/api.schemas'

import { PULSE_TILES, pulsePinLimitReason, todayHighlightsLogic } from './todayHighlightsLogic'
import {
    EditorGroup,
    changedKey,
    editorNotes,
    editorRows,
    suggestionsOnHome,
    withoutKeys,
} from './todayPulseEditorRows'

export function TodayPulseEditor(): JSX.Element {
    const {
        pulsePins,
        pulseSlots,
        pulseSuggestions,
        pulseRecentInsights,
        pulseRecentInsightsLoading,
        pulseRecentInsightsFailed,
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
    const [pinnedThisTime, setPinnedThisTime] = useState<PulsePinApi[]>([])

    const searching = search.trim().length > 0
    const pinnedKeys = new Set(pulsePins.map((pin) => pin.key))
    const searchFailedOrLoading = pulseInsightResultsLoading || pulseInsightSearchFailed
    const { groups, rowByKey, shownKeys, rowCount } = editorRows({
        search,
        pulsePins,
        pinnedOnOpen,
        othersOnOpen,
        pinnedThisTime,
        recentInsights: pulseRecentInsights,
        searchInsights: searchFailedOrLoading ? [] : pulseInsightResults,
    })
    const { statusNote, emptyNote } = searching
        ? editorNotes(true, rowCount, pulseInsightResultsLoading, pulseInsightSearchFailed)
        : editorNotes(false, rowCount, pulseRecentInsightsLoading, pulseRecentInsightsFailed)

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
                    const onHome = suggestionsOnHome(pulseSlots, pinnedKeys, pulseSuggestions)
                    setPinnedOnOpen(pulsePins)
                    setOthersOnOpen([
                        ...onHome,
                        ...withoutKeys(pulseSuggestions, new Set([...pinnedKeys, ...onHome.map((row) => row.key)])),
                    ])
                    setPinnedThisTime([])
                } else {
                    setSearch('')
                }
            }}
            onValueChange={(next: string[]) => {
                const row = rowByKey.get(changedKey(pinnedKeys, new Set(next)) ?? '')
                if (!row) {
                    return
                }
                if (!shownKeys.has(row.key)) {
                    setPinnedThisTime((rows) => [...rows, row])
                }
                togglePulsePin(row, 'editor')
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
                {statusNote ? (
                    <Text size="xs" variant="muted" render={<p />} className="m-0 px-2.5 py-1.5">
                        {statusNote}
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
