import type { HiddenPulseNumberApi, PulsePinApi, PulseSlotApi } from 'products/today/frontend/generated/api.schemas'

import { productNumberKind } from './todayPulseProductNumbers'

export const IGNORED_TOGGLE = 'today-pulse-editor:ignored'
const IGNORED_PREFIX = 'today-pulse-editor:ignored:'

export interface EditorGroup {
    kind: 'pinned' | 'others' | 'ignored'
    items: string[]
}

export function withoutKeys(rows: PulsePinApi[], keys: Set<string>): PulsePinApi[] {
    return rows.filter((row) => !keys.has(row.key))
}

function searchResults(search: string, listed: PulsePinApi[], insights: PulsePinApi[]): PulsePinApi[] {
    const query = search.trim().toLowerCase()
    const matches = listed.filter((row) => row.name.toLowerCase().includes(query))
    return [...matches, ...withoutKeys(insights, new Set(matches.map((row) => row.key)))]
}

export function suggestionsOnHome(
    slots: PulseSlotApi[],
    pinnedKeys: Set<string>,
    suggestions: PulsePinApi[]
): PulsePinApi[] {
    return slots
        .filter((slot) => !pinnedKeys.has(slot.key))
        .map((slot) => ({
            key: slot.key,
            name: slot.name,
            dashboard_id: suggestions.find((row) => row.key === slot.key)?.dashboard_id ?? null,
        }))
}

export function editorNotes(
    searching: boolean,
    rowCount: number,
    loading: boolean,
    failed: boolean
): { statusNote: string | null; emptyNote: string } {
    const emptyNote = searching ? 'No insights you can pin match your search' : 'No trend insights to pin yet'
    if (rowCount > 0 || !(loading || failed)) {
        return { statusNote: null, emptyNote }
    }
    if (loading) {
        return { statusNote: searching ? 'Searching…' : 'Loading your insights…', emptyNote }
    }
    return {
        statusNote: searching
            ? "Couldn't search your insights. Try again."
            : "Couldn't load your insights. Close and open Edit to try again.",
        emptyNote,
    }
}

interface EditorRows {
    groups: EditorGroup[]
    rowByKey: Map<string, PulsePinApi>
    ignoredByValue: Map<string, HiddenPulseNumberApi>
    shownKeys: Set<string>
    rowCount: number
}

export function editorRows({
    search,
    pulsePins,
    pinnedOnOpen,
    othersOnOpen,
    pinnedThisTime,
    recentInsights,
    searchInsights,
    ignored,
    ignoredOpen,
}: {
    search: string
    pulsePins: PulsePinApi[]
    pinnedOnOpen: PulsePinApi[]
    othersOnOpen: PulsePinApi[]
    pinnedThisTime: PulsePinApi[]
    recentInsights: PulsePinApi[]
    searchInsights: PulsePinApi[]
    ignored: HiddenPulseNumberApi[]
    ignoredOpen: boolean
}): EditorRows {
    const ignoredKeys = new Set(ignored.map((row) => row.key))
    const others = withoutKeys(othersOnOpen, ignoredKeys).filter((row) => !productNumberKind(row.key))
    const baseKeys = new Set([...pinnedOnOpen, ...others].map((row) => row.key))
    const recent = withoutKeys(
        recentInsights,
        new Set([...baseKeys, ...ignoredKeys, ...pinnedThisTime.map((row) => row.key)])
    )
    const shownKeys = new Set([...baseKeys, ...recent.map((row) => row.key)])
    const extraPinned = withoutKeys(uniqueRows([...pinnedThisTime, ...pulsePins]), shownKeys)
    const pinnedRows = [...pinnedOnOpen, ...extraPinned]
    const results = searchResults(search, [...pinnedRows, ...others, ...recent], searchInsights)
    const rowByKey = new Map(
        [...pulsePins, ...pinnedRows, ...others, ...recent, ...results].map((row) => [row.key, row])
    )
    const ignoredByValue = new Map(ignored.map((row) => [`${IGNORED_PREFIX}${row.key}`, row]))
    const groups: EditorGroup[] = (
        search.trim()
            ? [{ kind: 'others' as const, items: results.map((row) => row.key) }]
            : [
                  { kind: 'pinned' as const, items: pinnedRows.map((row) => row.key) },
                  { kind: 'others' as const, items: [...others, ...recent].map((row) => row.key) },
                  {
                      kind: 'ignored' as const,
                      items: ignored.length ? [IGNORED_TOGGLE, ...(ignoredOpen ? [...ignoredByValue.keys()] : [])] : [],
                  },
              ]
    ).filter((group) => group.items.length > 0)
    return {
        groups,
        rowByKey,
        ignoredByValue,
        shownKeys: new Set([...shownKeys, ...pinnedRows.map((row) => row.key)]),
        rowCount: groups.reduce((count, group) => count + (group.kind === 'ignored' ? 0 : group.items.length), 0),
    }
}

function uniqueRows(rows: PulsePinApi[]): PulsePinApi[] {
    return rows.filter((row, index) => rows.findIndex((other) => other.key === row.key) === index)
}

export function changedKey(before: Set<string>, after: Set<string>): string | undefined {
    return [...after].find((key) => !before.has(key)) ?? [...before].find((key) => !after.has(key))
}
