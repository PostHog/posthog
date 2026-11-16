import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconHide, IconSearch } from '@posthog/icons'
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

import type { HiddenPulseNumberApi, PulsePinApi } from 'products/today/frontend/generated/api.schemas'

import { PULSE_TILES, pulsePinLimitReason, todayHighlightsLogic } from './todayHighlightsLogic'
import {
    EditorGroup,
    IGNORED_TOGGLE,
    changedKey,
    editorNotes,
    editorRows,
    suggestionsOnHome,
    withoutKeys,
} from './todayPulseEditorRows'
import { TodayPulseInsightHover } from './TodayPulseInsightHover'

function IgnoredToggleItem({ count, open }: { count: number; open: boolean }): JSX.Element {
    const Chevron = open ? IconChevronDown : IconChevronRight
    return (
        <ComboboxItem
            value={IGNORED_TOGGLE}
            action
            aria-expanded={open}
            className="pe-8 text-muted-foreground"
            data-attr="today-pulse-ignored-toggle"
        >
            <IconHide className="size-3.5 shrink-0" />
            <span className="min-w-0 truncate">Ignored</span>
            <span className="text-xs tabular-nums">{count}</span>
            <Chevron className="pointer-events-none absolute end-2 size-3.5" />
        </ComboboxItem>
    )
}

function IgnoredItem({ value, row }: { value: string; row: HiddenPulseNumberApi }): JSX.Element {
    return (
        <ComboboxItem
            value={value}
            tooltip="It can be suggested again"
            className="pe-16 text-muted-foreground"
            data-attr="today-pulse-restore"
        >
            <span className="min-w-0 truncate">{row.name}</span>
            <span className="pointer-events-none absolute end-2.5 text-xs">Restore</span>
        </ComboboxItem>
    )
}

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
        pulseHidden,
    } = useValues(todayHighlightsLogic)
    const { togglePulsePin, loadPulseInsightResults, pulseEditorOpened, restoreHiddenPulseNumber } =
        useActions(todayHighlightsLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const listRef = useRef<HTMLDivElement>(null)
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    const [ignoredOpen, setIgnoredOpen] = useState(false)
    const [pinnedOnOpen, setPinnedOnOpen] = useState<PulsePinApi[]>([])
    const [othersOnOpen, setOthersOnOpen] = useState<PulsePinApi[]>([])
    const [pinnedThisTime, setPinnedThisTime] = useState<PulsePinApi[]>([])

    useEffect(() => {
        if (ignoredOpen) {
            listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
        }
    }, [ignoredOpen])

    const searching = search.trim().length > 0
    const pinnedKeys = new Set(pulsePins.map((pin) => pin.key))
    const searchFailedOrLoading = pulseInsightResultsLoading || pulseInsightSearchFailed
    const { groups, rowByKey, ignoredByValue, shownKeys, rowCount } = editorRows({
        search,
        pulsePins,
        pinnedOnOpen,
        othersOnOpen,
        pinnedThisTime,
        recentInsights: pulseRecentInsights,
        searchInsights: searchFailedOrLoading ? [] : pulseInsightResults,
        ignored: pulseHidden,
        ignoredOpen,
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
            itemToStringLabel={(key: string) =>
                key === IGNORED_TOGGLE ? 'Ignored' : ((ignoredByValue.get(key) ?? rowByKey.get(key))?.name ?? '')
            }
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
                    setIgnoredOpen(false)
                }
            }}
            onValueChange={(next: string[]) => {
                const key = changedKey(pinnedKeys, new Set(next)) ?? ''
                const ignored = ignoredByValue.get(key)
                if (key === IGNORED_TOGGLE) {
                    setIgnoredOpen((value) => !value)
                    return
                }
                if (ignored) {
                    restoreHiddenPulseNumber(ignored)
                    return
                }
                const row = rowByKey.get(key)
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
                <ComboboxList ref={listRef}>
                    {(group: EditorGroup) => (
                        <ComboboxGroup key={group.kind} items={group.items}>
                            {group.kind !== groups[0]?.kind ? <ComboboxSeparator /> : null}
                            <ComboboxCollection>
                                {(key: string) => {
                                    const ignored = ignoredByValue.get(key)
                                    if (key === IGNORED_TOGGLE) {
                                        return (
                                            <IgnoredToggleItem
                                                key={key}
                                                count={pulseHidden.length}
                                                open={ignoredOpen}
                                            />
                                        )
                                    }
                                    if (ignored) {
                                        return <IgnoredItem key={key} value={key} row={ignored} />
                                    }
                                    const pinned = pinnedKeys.has(key)
                                    const item = (
                                        <ComboboxItem
                                            key={key}
                                            value={key}
                                            disabledReason={
                                                pulsePinsUnavailableReason ??
                                                pulsePinLimitReason(pulsePins.length, pinned)
                                            }
                                            data-attr="today-pulse-pin"
                                        >
                                            <span className="min-w-0 truncate">{rowByKey.get(key)?.name}</span>
                                        </ComboboxItem>
                                    )
                                    return key.startsWith('insight:') ? (
                                        <TodayPulseInsightHover key={key} shortId={key.slice('insight:'.length)}>
                                            {item}
                                        </TodayPulseInsightHover>
                                    ) : (
                                        item
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
