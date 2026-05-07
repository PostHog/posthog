import { MutableRefObject, ReactNode, RefCallback, useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type BulkSelectionKey = string | number

export interface BulkSelectionHandle {
    setSelectedKeys: (keys: ReadonlyArray<BulkSelectionKey>) => void
    clearSelection: () => void
    getSelectedKeys: () => ReadonlyArray<BulkSelectionKey>
}

export type BulkSelectionRef =
    | RefCallback<BulkSelectionHandle | null>
    | MutableRefObject<BulkSelectionHandle | null>
    | null
    | undefined

export type BulkSelectionRowGate = true | false | { disabledReason: string }

export interface BulkSelectionContext<T> {
    /** Every key currently selected, including those on pages other than the current one. */
    selectedKeys: ReadonlyArray<BulkSelectionKey>
    /** Records on the current page that are selected. Records on other pages aren't available here. */
    selectedRecords: ReadonlyArray<T>
    /** Total number of selected keys (== selectedKeys.length). */
    selectedCount: number
    /** Clear the entire selection. */
    clearSelection: () => void
    /** Replace the selection with the given keys (e.g. for "select all matching across pages"). */
    setSelectedKeys: (keys: ReadonlyArray<BulkSelectionKey>) => void
}

export interface BulkSelectionConfig<T extends Record<string, any>> {
    /** Render bulk action UI shown above the table whenever `selectedCount > 0`. */
    renderActions: (ctx: BulkSelectionContext<T>) => ReactNode
    /** Per-row gate. Return `false` or `{ disabledReason }` to disable that row's checkbox. */
    isRowSelectable?: (record: T, rowIndex: number) => BulkSelectionRowGate
    /** Override how a record is mapped to a selection key. Defaults to LemonTable's `rowKey`. */
    getKey?: (record: T) => BulkSelectionKey
    /** aria-label for the per-row checkbox (receives the record). */
    rowAriaLabel?: (record: T) => string
    /** aria-label for the header "select all on page" checkbox. */
    headerAriaLabel?: string
    /** Singular/plural noun used in "N items selected". Defaults to ['item', 'items']. */
    noun?: [string, string]
    /** Imperative handle for callers that need to push selection in from outside the renderActions
     *  slot (e.g. to react to a kea loader resolving). The render-prop already exposes
     *  setSelectedKeys / clearSelection — only reach for this when those aren't enough. */
    handleRef?: BulkSelectionRef
}

export interface UseBulkSelectionResult<T> {
    selectedKeys: BulkSelectionKey[]
    selectedKeysSet: Set<BulkSelectionKey>
    isAllOnPageSelected: boolean
    isSomeOnPageSelected: boolean
    /** True when there is at least one selectable row on the page. Used to decide whether the
     *  header checkbox does anything. */
    pageHasSelectableRows: boolean
    toggleRow: (key: BulkSelectionKey, rowIndex: number) => void
    toggleAllOnPage: () => void
    clearSelection: () => void
    setSelectedKeys: (keys: ReadonlyArray<BulkSelectionKey>) => void
    context: BulkSelectionContext<T>
}

export interface UseBulkSelectionParams<T extends Record<string, any>> {
    pageRecords: T[]
    getKey: (record: T) => BulkSelectionKey
    isRowSelectable?: (record: T, rowIndex: number) => BulkSelectionRowGate
    handleRef?: BulkSelectionRef
}

function gateAllowsSelection(gate: BulkSelectionRowGate): boolean {
    if (gate === true) {
        return true
    }
    if (gate === false) {
        return false
    }
    return false
}

function assignBulkSelectionRef(ref: BulkSelectionRef, value: BulkSelectionHandle | null): void {
    if (!ref) {
        return
    }
    if (typeof ref === 'function') {
        ref(value)
        return
    }
    ref.current = value
}

export function useBulkSelection<T extends Record<string, any>>({
    pageRecords,
    getKey,
    isRowSelectable,
    handleRef,
}: UseBulkSelectionParams<T>): UseBulkSelectionResult<T> {
    const [selectedKeys, setSelectedKeysState] = useState<BulkSelectionKey[]>([])
    const previouslyCheckedIndexRef = useRef<number | null>(null)
    const shiftKeyHeldRef = useRef(false)
    const selectedKeysRef = useRef<BulkSelectionKey[]>(selectedKeys)
    selectedKeysRef.current = selectedKeys

    useEffect(() => {
        const onKeyChange = (event: KeyboardEvent): void => {
            shiftKeyHeldRef.current = event.shiftKey
        }
        window.addEventListener('keydown', onKeyChange)
        window.addEventListener('keyup', onKeyChange)
        return () => {
            window.removeEventListener('keydown', onKeyChange)
            window.removeEventListener('keyup', onKeyChange)
        }
    }, [])

    const selectedKeysSet = useMemo(() => new Set(selectedKeys), [selectedKeys])

    const selectableKeysOnPage = useMemo<BulkSelectionKey[]>(() => {
        const keys: BulkSelectionKey[] = []
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

    const setSelectedKeys = useCallback((keys: ReadonlyArray<BulkSelectionKey>): void => {
        setSelectedKeysState(Array.from(new Set(keys)))
    }, [])

    const clearSelection = useCallback((): void => {
        setSelectedKeysState([])
        previouslyCheckedIndexRef.current = null
    }, [])

    const toggleRow = useCallback(
        (key: BulkSelectionKey, rowIndex: number): void => {
            setSelectedKeysState((current) => {
                const currentSet = new Set(current)
                const previouslyCheckedIndex = previouslyCheckedIndexRef.current

                if (shiftKeyHeldRef.current && previouslyCheckedIndex !== null) {
                    const start = Math.min(previouslyCheckedIndex, rowIndex)
                    const end = Math.max(previouslyCheckedIndex, rowIndex)
                    const rangeKeys: BulkSelectionKey[] = []
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
            previouslyCheckedIndexRef.current = rowIndex
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

    const context = useMemo<BulkSelectionContext<T>>(
        () => ({
            selectedKeys,
            selectedRecords,
            selectedCount: selectedKeys.length,
            clearSelection,
            setSelectedKeys,
        }),
        [selectedKeys, selectedRecords, clearSelection, setSelectedKeys]
    )

    useEffect(() => {
        if (!handleRef) {
            return
        }
        const handle: BulkSelectionHandle = {
            setSelectedKeys,
            clearSelection,
            getSelectedKeys: () => selectedKeysRef.current,
        }
        assignBulkSelectionRef(handleRef, handle)
        return () => {
            assignBulkSelectionRef(handleRef, null)
        }
    }, [handleRef, setSelectedKeys, clearSelection])

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
