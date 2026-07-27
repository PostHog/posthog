import { ReactNode, useCallback, useMemo, useRef, useState } from 'react'

export type BulkSelectionKey = string | number

export type BulkSelectionRowGate = true | false | { disabledReason: string }

export interface BulkSelectionContext<T, K extends BulkSelectionKey = BulkSelectionKey> {
    /** Every key currently selected, including those on pages other than the current one. */
    selectedKeys: ReadonlyArray<K>
    /** Records on the current page that are selected. Records on other pages aren't available here. */
    selectedRecords: ReadonlyArray<T>
    /** Total number of selected keys (== selectedKeys.length). */
    selectedCount: number
    /** Clear the entire selection. */
    clearSelection: () => void
    /** Replace the selection with the given keys (e.g. for "select all matching across pages"). */
    setSelectedKeys: (keys: ReadonlyArray<K>) => void
}

export interface BulkSelectionConfig<T extends Record<string, any>, K extends BulkSelectionKey = BulkSelectionKey> {
    /** Render bulk action UI shown above the table whenever `selectedCount > 0`. */
    renderActions: (ctx: BulkSelectionContext<T, K>) => ReactNode
    /** Per-row gate. Return `false` or `{ disabledReason }` to disable that row's checkbox. */
    isRowSelectable?: (record: T, rowIndex: number) => BulkSelectionRowGate
    /** Override how a record is mapped to a selection key. Defaults to LemonTable's `rowKey`.
     *  The function MUST be deterministic per-record (depend on the record only, not the row
     *  index) — selection identity is keyed by the return value, so an index-dependent rowKey
     *  would collapse selection to whatever the function returns at index 0. */
    getKey?: (record: T) => K
    /** aria-label for the per-row checkbox (receives the record). */
    rowAriaLabel?: (record: T) => string
    /** aria-label for the header "select all on page" checkbox. */
    headerAriaLabel?: string
    /** Singular/plural noun used in "N items selected". Defaults to ['item', 'items']. */
    noun?: [string, string]
    /** Initial selection (uncontrolled). Read once on mount; later changes are ignored.
     *  Useful for stories and test scaffolds that want to render the bar pre-populated. */
    initialSelectedKeys?: ReadonlyArray<K>
    /** Extra classes for the bulk-action bar wrapper (e.g. spacing). Opt-in so other tables are unaffected. */
    barClassName?: string
    /** Render the bar into this element (via portal) instead of above the table — lets callers place
     *  it inline with an existing toolbar row. While the element is null (not mounted yet), the bar
     *  falls back to its default position above the table. */
    barPortalTarget?: HTMLElement | null
}

export interface UseBulkSelectionResult<T, K extends BulkSelectionKey = BulkSelectionKey> {
    selectedKeys: K[]
    selectedKeysSet: Set<K>
    isAllOnPageSelected: boolean
    isSomeOnPageSelected: boolean
    /** True when there is at least one selectable row on the page. Used to decide whether the
     *  header checkbox does anything. */
    pageHasSelectableRows: boolean
    toggleRow: (key: K, rowIndex: number, shiftKeyHeld?: boolean) => void
    toggleAllOnPage: () => void
    clearSelection: () => void
    setSelectedKeys: (keys: ReadonlyArray<K>) => void
    context: BulkSelectionContext<T, K>
}

export interface UseBulkSelectionParams<T extends Record<string, any>, K extends BulkSelectionKey = BulkSelectionKey> {
    pageRecords: T[]
    getKey: (record: T) => K
    isRowSelectable?: (record: T, rowIndex: number) => BulkSelectionRowGate
    initialSelectedKeys?: ReadonlyArray<K>
}

function gateAllowsSelection(gate: BulkSelectionRowGate): boolean {
    return gate === true
}

export function useBulkSelection<T extends Record<string, any>, K extends BulkSelectionKey = BulkSelectionKey>({
    pageRecords,
    getKey,
    isRowSelectable,
    initialSelectedKeys,
}: UseBulkSelectionParams<T, K>): UseBulkSelectionResult<T, K> {
    const [selectedKeys, setSelectedKeysState] = useState<K[]>(() =>
        initialSelectedKeys ? Array.from(new Set(initialSelectedKeys)) : []
    )
    const previouslyCheckedIndexRef = useRef<number | null>(null)

    const selectedKeysSet = useMemo(() => new Set(selectedKeys), [selectedKeys])

    const selectableKeysOnPage = useMemo<K[]>(() => {
        const keys: K[] = []
        pageRecords.forEach((record, index) => {
            const gate: BulkSelectionRowGate = isRowSelectable ? isRowSelectable(record, index) : true
            if (gateAllowsSelection(gate)) {
                keys.push(getKey(record))
            }
        })
        return keys
    }, [pageRecords, getKey, isRowSelectable])

    const isAllOnPageSelected =
        selectableKeysOnPage.length > 0 && selectableKeysOnPage.every((key) => selectedKeysSet.has(key))
    const isSomeOnPageSelected = !isAllOnPageSelected && selectableKeysOnPage.some((key) => selectedKeysSet.has(key))

    const setSelectedKeys = useCallback((keys: ReadonlyArray<K>): void => {
        setSelectedKeysState(Array.from(new Set(keys)))
    }, [])

    const clearSelection = useCallback((): void => {
        setSelectedKeysState([])
        previouslyCheckedIndexRef.current = null
    }, [])

    const toggleRow = useCallback(
        (key: K, rowIndex: number, shiftKeyHeld: boolean = false): void => {
            // Capture the anchor index *outside* the state setter — it could be invoked
            // asynchronously (concurrent rendering) and re-reading the ref then would already see
            // the value we're about to write below.
            const previouslyCheckedIndex = previouslyCheckedIndexRef.current
            previouslyCheckedIndexRef.current = rowIndex
            setSelectedKeysState((current) => {
                const currentSet = new Set(current)

                if (shiftKeyHeld && previouslyCheckedIndex !== null) {
                    const start = Math.min(previouslyCheckedIndex, rowIndex)
                    const end = Math.max(previouslyCheckedIndex, rowIndex)
                    const rangeKeys: K[] = []
                    for (let i = start; i <= end; i++) {
                        const record = pageRecords[i]
                        if (!record) {
                            continue
                        }
                        const gate: BulkSelectionRowGate = isRowSelectable ? isRowSelectable(record, i) : true
                        if (gateAllowsSelection(gate)) {
                            rangeKeys.push(getKey(record))
                        }
                    }
                    const isDeselecting = currentSet.has(key)
                    if (isDeselecting) {
                        const rangeSet = new Set(rangeKeys)
                        return current.filter((k) => !rangeSet.has(k))
                    }
                    return Array.from(new Set([...current, ...rangeKeys]))
                }

                if (currentSet.has(key)) {
                    return current.filter((k) => k !== key)
                }
                return [...current, key]
            })
        },
        [pageRecords, getKey, isRowSelectable]
    )

    const toggleAllOnPage = useCallback((): void => {
        if (selectableKeysOnPage.length === 0) {
            return
        }
        setSelectedKeysState((current) => {
            const currentSet = new Set(current)
            const allSelected = selectableKeysOnPage.every((key) => currentSet.has(key))
            if (allSelected) {
                const pageSet = new Set(selectableKeysOnPage)
                return current.filter((k) => !pageSet.has(k))
            }
            return Array.from(new Set([...current, ...selectableKeysOnPage]))
        })
    }, [selectableKeysOnPage])

    const selectedRecords = useMemo<T[]>(
        () => pageRecords.filter((record) => selectedKeysSet.has(getKey(record))),
        [pageRecords, selectedKeysSet, getKey]
    )

    const context = useMemo<BulkSelectionContext<T, K>>(
        () => ({
            selectedKeys,
            selectedRecords,
            selectedCount: selectedKeys.length,
            clearSelection,
            setSelectedKeys,
        }),
        [selectedKeys, selectedRecords, clearSelection, setSelectedKeys]
    )

    return {
        selectedKeys,
        selectedKeysSet,
        isAllOnPageSelected,
        isSomeOnPageSelected,
        pageHasSelectableRows: selectableKeysOnPage.length > 0,
        toggleRow,
        toggleAllOnPage,
        clearSelection,
        setSelectedKeys,
        context,
    }
}
