import React, {
    ReactNode,
    cloneElement,
    createContext,
    forwardRef,
    isValidElement,
    useCallback,
    useContext,
    useEffect,
    useImperativeHandle,
    useMemo,
    useRef,
    useState,
} from 'react'

import { cn } from 'lib/utils/css-classes'

/** Imperative API handle for Combobox to call focusFirstItem() etc */
export interface ListBoxHandle {
    recalculateFocusableElements: () => void
    focusFirstItem: () => void
    getFocusableElementsCount: () => number
    focusItemByKey: (key: string) => boolean
    focusPrevious: (stepsBack?: number) => boolean
    getFocusHistory: () => string[]
}

/** Imperative API handle for ListBox.Group */
export interface ListBoxGroupHandle {
    resumeFocus: (index: number) => boolean
    getFocusedIndex: () => number | null
}

/** Context to expose container ref to child Items */
interface ListBoxContextType {
    containerRef: React.RefObject<HTMLDivElement> | null
    registerGroupItem?: (groupId: string, index: number, element: HTMLLIElement) => void
    unregisterGroupItem?: (groupId: string, index: number) => void
    focusGroupItem?: (groupId: string, index: number) => boolean
}

const ListBoxContext = createContext<ListBoxContextType>({ containerRef: null })

/** Context for ListBox.Group to track its own items */
interface ListBoxGroupContextType {
    groupId: string
    registerItem: (index: number, element: HTMLLIElement) => void
    unregisterItem: (index: number) => void
}

const ListBoxGroupContext = createContext<ListBoxGroupContextType | null>(null)

/** Props for ListBox */
interface ListBoxProps extends React.HTMLAttributes<HTMLDivElement> {
    children: ReactNode
    className?: string
    focusedElement?: HTMLElement | null
    virtualFocus?: boolean
    autoSelectFirst?: boolean
    onFinishedKeyDown?: ({
        e,
        activeElement,
        nextFocusedElement,
        allElements,
    }: {
        e: React.KeyboardEvent
        activeElement: HTMLElement | null
        nextFocusedElement: HTMLElement | null
        allElements: HTMLElement[]
    }) => void
}

/** Root ListBox implementation */
const InnerListBox = forwardRef<ListBoxHandle, ListBoxProps>(function ListBox(
    { children, className, onFinishedKeyDown, focusedElement, virtualFocus = false, autoSelectFirst = false, ...props },
    ref
) {
    const containerRef = useRef<HTMLDivElement>(null)
    const focusableElements = useRef<HTMLElement[]>([])
    const rows = useRef<HTMLElement[][]>([])
    const columnHeights = useRef<number[]>([])
    const stickyRowRef = useRef<number | null>(null)
    const maxColumnIndexRef = useRef<number>(-1)
    const [virtualFocusedElementState, setVirtualFocusedElementState] = useState<HTMLElement | null>(null)
    const focusHistory = useRef<string[]>([])
    const MAX_FOCUS_HISTORY = 10 // Keep last 10 focus keys
    const suppressAutoFocus = useRef<boolean>(false) // Flag to temporarily suppress autoSelectFirst

    // Group management
    const groups = useRef<Map<string, Map<number, HTMLElement>>>(new Map())

    // Wrapper to track focus history for virtual focus changes
    const setVirtualFocusedElement = useCallback((element: HTMLElement | null) => {
        // Manually dispatch focus event for virtual focus changes to maintain focus history
        if (element && containerRef.current) {
            const focusKey = element.getAttribute('data-focus-key')
            if (focusKey) {
                const isContent = !focusKey.startsWith('show-all-')
                containerRef.current.dispatchEvent(
                    new CustomEvent('listbox:setFocusKey', {
                        detail: { focusKey, isContent },
                        bubbles: true,
                    })
                )
            }
        }

        setVirtualFocusedElementState(element)
    }, [])

    const recalculateFocusableElements = useCallback((): void => {
        focusableElements.current = Array.from(
            containerRef.current?.querySelectorAll<HTMLElement>('[data-listbox-item]') || []
        ).filter(
            (el) =>
                !(el.hidden || window.getComputedStyle(el).display === 'none') &&
                el.getAttribute('aria-disabled') !== 'true' &&
                el.getAttribute('data-virtual-focus-ignore') !== 'true'
        )

        rows.current = []
        columnHeights.current = []
        maxColumnIndexRef.current = -1

        for (const el of focusableElements.current) {
            if (!el.hasAttribute('data-row') || !el.hasAttribute('data-column')) {
                continue
            }
            const row = parseInt(el.getAttribute('data-row') || '0', 10)
            const column = parseInt(el.getAttribute('data-column') || '0', 10)

            if (!rows.current[row]) {
                rows.current[row] = []
            }
            rows.current[row][column] = el

            // track per-column max row
            columnHeights.current[column] = Math.max(columnHeights.current[column] ?? -1, row)
            maxColumnIndexRef.current = Math.max(maxColumnIndexRef.current, column)
        }
    }, [])

    const addToFocusHistory = useCallback(
        (focusKey: string): void => {
            // Don't add if it's the same as the last item
            if (focusHistory.current[focusHistory.current.length - 1] === focusKey) {
                return
            }

            // Add to history
            focusHistory.current.push(focusKey)

            // Trim to max length
            if (focusHistory.current.length > MAX_FOCUS_HISTORY) {
                focusHistory.current = focusHistory.current.slice(-MAX_FOCUS_HISTORY)
            }
        },
        [MAX_FOCUS_HISTORY]
    )

    useEffect(() => {
        const el = containerRef.current
        if (!el) {
            return
        }
        const stickyRowHandler = (ev: Event): void => {
            const row = (ev as CustomEvent).detail?.row
            if (typeof row === 'number' && row >= 0) {
                stickyRowRef.current = row
            }
        }
        const focusHandler = (ev: Event): void => {
            const detail = (ev as CustomEvent).detail
            const focusKey = detail?.focusKey

            if (typeof focusKey === 'string') {
                addToFocusHistory(focusKey)
            }
        }
        el.addEventListener('listbox:setStickyRow', stickyRowHandler as EventListener)
        el.addEventListener('listbox:setFocusKey', focusHandler as EventListener)
        return () => {
            el.removeEventListener('listbox:setStickyRow', stickyRowHandler as EventListener)
            el.removeEventListener('listbox:setFocusKey', focusHandler as EventListener)
        }
    }, [addToFocusHistory])

    const gridPosition = useMemo<{ row: number; column: number }>(() => {
        const activeElement = virtualFocus ? virtualFocusedElementState : (document.activeElement as HTMLElement)
        for (const el of focusableElements.current) {
            if (el.hasAttribute('data-row') && el.hasAttribute('data-column')) {
                const row = parseInt(el.getAttribute('data-row') || '0', 10)
                const column = parseInt(el.getAttribute('data-column') || '0', 10)
                if (el === activeElement) {
                    return { row, column }
                }
            }
        }
        return { row: -1, column: -1 }
    }, [virtualFocus, virtualFocusedElementState])

    const focusFirstItem = useCallback(() => {
        recalculateFocusableElements()
        const elements = focusableElements.current
        if (!elements.length) {
            return
        }

        elements.forEach((el) => el.removeAttribute('data-focused'))

        // Find first element with data-focus-first="true", otherwise use first element
        const firstFocusElement = elements.find((el) => el.getAttribute('data-focus-first') === 'true') || elements[0]

        if (virtualFocus) {
            setVirtualFocusedElement(firstFocusElement)
            firstFocusElement.setAttribute('data-focused', 'true')
            const r = firstFocusElement.getAttribute('data-row')
            stickyRowRef.current = r ? parseInt(r, 10) : 0
        } else {
            firstFocusElement.focus()
        }
    }, [virtualFocus, recalculateFocusableElements, setVirtualFocusedElement])

    const getFocusableElementsCount = useCallback(() => {
        recalculateFocusableElements()
        const elements = focusableElements.current
        if (!elements.length) {
            return 0
        }
        return elements.length
    }, [recalculateFocusableElements])

    const focusItemByKey = useCallback(
        (key: string): boolean => {
            recalculateFocusableElements()
            const elements = focusableElements.current
            const targetElement = elements.find((el) => el.getAttribute('data-focus-key') === key)

            if (!targetElement) {
                return false
            }

            elements.forEach((el) => el.removeAttribute('data-focused'))

            if (virtualFocus) {
                setVirtualFocusedElement(targetElement)
                targetElement.setAttribute('data-focused', 'true')
                const r = targetElement.getAttribute('data-row')
                stickyRowRef.current = r ? parseInt(r, 10) : 0
            } else {
                targetElement.focus()
            }

            targetElement.scrollIntoView({ block: 'nearest' })
            return true
        },
        [virtualFocus, recalculateFocusableElements, setVirtualFocusedElement]
    )

    const focusPrevious = useCallback(
        (stepsBack = 1): boolean => {
            // Set flag to suppress auto focus during the next render cycle
            suppressAutoFocus.current = true

            if (focusHistory.current.length === 0 || stepsBack <= 0) {
                return false
            }

            // Find the Nth content item from the end (skipping "show-all" buttons)
            let contentItemsFound = 0
            for (let i = focusHistory.current.length - 1; i >= 0; i--) {
                const focusKey = focusHistory.current[i]

                // Skip "show-all" buttons
                if (focusKey.startsWith('show-all-')) {
                    continue
                }

                contentItemsFound++

                if (contentItemsFound === stepsBack) {
                    const result = focusItemByKey(focusKey)

                    // Reset the suppress flag after a brief delay to allow normal auto-focus later
                    setTimeout(() => {
                        suppressAutoFocus.current = false
                    }, 100)

                    return result
                }
            }

            // Reset the suppress flag even if we didn't find anything
            setTimeout(() => {
                suppressAutoFocus.current = false
            }, 100)
            return false
        },
        [focusItemByKey]
    )

    const getFocusHistory = useCallback((): string[] => {
        return [...focusHistory.current]
    }, [])

    // Group management functions
    const registerGroupItem = useCallback((groupId: string, index: number, element: HTMLLIElement) => {
        if (!groups.current.has(groupId)) {
            groups.current.set(groupId, new Map())
        }
        groups.current.get(groupId)!.set(index, element)
    }, [])

    const unregisterGroupItem = useCallback((groupId: string, index: number) => {
        groups.current.get(groupId)?.delete(index)
        if (groups.current.get(groupId)?.size === 0) {
            groups.current.delete(groupId)
        }
    }, [])

    const focusGroupItem = useCallback(
        (groupId: string, index: number): boolean => {
            const group = groups.current.get(groupId)
            const element = group?.get(index)

            if (!element) {
                return false
            }

            // Use existing focusItemByKey if the element has a focus key, otherwise focus directly
            const focusKey = element.getAttribute('data-focus-key')
            if (focusKey) {
                return focusItemByKey(focusKey)
            }
            // Focus directly
            focusableElements.current.forEach((el) => el.removeAttribute('data-focused'))

            if (virtualFocus) {
                setVirtualFocusedElement(element)
                element.setAttribute('data-focused', 'true')
                const r = element.getAttribute('data-row')
                stickyRowRef.current = r ? parseInt(r, 10) : 0
            } else {
                element.focus()
            }

            element.scrollIntoView({ block: 'nearest' })
            return true
        },
        [focusItemByKey, virtualFocus, setVirtualFocusedElement]
    )

    useImperativeHandle(
        ref,
        () => ({
            recalculateFocusableElements,
            focusFirstItem,
            getFocusableElementsCount,
            focusItemByKey,
            focusPrevious,
            getFocusHistory,
        }),
        [
            recalculateFocusableElements,
            focusFirstItem,
            getFocusableElementsCount,
            focusItemByKey,
            focusPrevious,
            getFocusHistory,
        ]
    )

    // helper to derive row/column from an element
    const getRC = (el: HTMLElement | null): { row: number; column: number } => {
        if (!el) {
            return { row: -1, column: -1 }
        }
        const row = parseInt(el.getAttribute('data-row') || '-1', 10)
        const column = parseInt(el.getAttribute('data-column') || '-1', 10)
        return { row, column }
    }

    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent): void => {
            if (!containerRef.current?.contains(document.activeElement)) {
                return
            }

            recalculateFocusableElements()
            const elements = focusableElements.current
            if (!elements.length) {
                return
            }

            const activeElement = virtualFocus ? virtualFocusedElementState : (document.activeElement as HTMLElement)
            const { row: curRow } = getRC(activeElement)

            // Always refresh sticky row to reflect *current* position.
            if (curRow >= 0) {
                stickyRowRef.current = curRow
            }

            const currentIndex = elements.indexOf(activeElement!)
            let nextIndex = currentIndex
            let handledArrowNavigation = false

            if (virtualFocus) {
                elements.forEach((el) => el.removeAttribute('data-focused'))
            }

            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault()
                handledArrowNavigation = true

                // If current element is not in the list (like focusing from input), prioritize focusFirst items
                if (currentIndex === -1) {
                    if (e.key === 'ArrowDown') {
                        const firstFocusElement = elements.find((el) => el.getAttribute('data-focus-first') === 'true')
                        nextIndex = firstFocusElement ? elements.indexOf(firstFocusElement) : 0
                    } else {
                        nextIndex = elements.length - 1
                    }
                } else {
                    nextIndex = (currentIndex + (e.key === 'ArrowDown' ? 1 : -1) + elements.length) % elements.length
                }
                if (handledArrowNavigation) {
                    const targetEl = elements[nextIndex]
                    const { row: newRow } = getRC(targetEl)
                    if (newRow >= 0) {
                        stickyRowRef.current = newRow
                    }

                    if (virtualFocus) {
                        setVirtualFocusedElement(targetEl)
                        targetEl?.setAttribute('data-focused', 'true')
                    } else {
                        targetEl?.focus()
                    }
                    targetEl?.scrollIntoView({ block: 'nearest' })
                }
            } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                if (gridPosition.row === -1 || gridPosition.column === -1) {
                    return
                }

                // ensure we have a sticky row to aim for (now always the current row)
                const desiredRow = stickyRowRef.current ?? gridPosition.row
                const dir = e.key === 'ArrowLeft' ? -1 : 1

                // step to the next existing column in that direction
                let targetCol = gridPosition.column + dir
                const colInBounds = (c: number): boolean => c >= 0 && c <= maxColumnIndexRef.current

                // skip completely empty columns if any
                while (colInBounds(targetCol) && (columnHeights.current[targetCol] ?? -1) < 0) {
                    targetCol += dir
                }

                // === EDGE BEHAVIOR ===
                // If there is no column in that direction, keep selection as-is.
                // If virtualFocus is true, DO NOT preventDefault so the input caret moves.
                if (!colInBounds(targetCol)) {
                    if (!virtualFocus) {
                        e.preventDefault()
                    } // avoid page scroll when focus is on list item
                    return
                }

                // if the column is tall enough, use desiredRow; else clamp to its bottom
                const colHeight = columnHeights.current[targetCol] ?? -1
                if (colHeight < 0) {
                    if (!virtualFocus) {
                        e.preventDefault()
                    }
                    return
                }

                const targetRow = Math.min(desiredRow, colHeight)

                // Try the exact spot (targetRow, targetCol)
                let nextEl = rows.current[targetRow]?.[targetCol]

                // Extremely defensive: if holes exist, search upward towards 0 until we find something
                if (!nextEl) {
                    for (let r = targetRow; r >= 0; r--) {
                        if (rows.current[r]?.[targetCol]) {
                            nextEl = rows.current[r][targetCol]
                            break
                        }
                    }
                }

                // If still nothing found, treat like edge: keep selection and possibly move caret
                if (!nextEl) {
                    if (!virtualFocus) {
                        e.preventDefault()
                    }
                    return
                }

                // We ARE moving selection → prevent default and move focus/virtual focus
                e.preventDefault()

                // IMPORTANT: keep stickyRowRef as the *desired* row (do not overwrite with clamped row)
                if (virtualFocus) {
                    setVirtualFocusedElement(nextEl)
                    nextEl.setAttribute('data-focused', 'true')
                } else {
                    nextEl.focus()
                }
                nextEl.scrollIntoView({ block: 'nearest' })
            } else if (e.key === 'Home' || e.key === 'End') {
                e.preventDefault()
                handledArrowNavigation = true
                if (e.key === 'Home') {
                    const firstFocusElement = elements.find((el) => el.getAttribute('data-focus-first') === 'true')
                    nextIndex = firstFocusElement ? elements.indexOf(firstFocusElement) : 0
                } else {
                    nextIndex = elements.length - 1
                }
            }

            if (handledArrowNavigation) {
                if (virtualFocus) {
                    setVirtualFocusedElement(elements[nextIndex])
                    elements[nextIndex]?.setAttribute('data-focused', 'true')
                } else {
                    elements[nextIndex]?.focus()
                }

                elements[nextIndex]?.scrollIntoView({ block: 'nearest' })
            }

            if (e.key === 'Enter') {
                e.preventDefault()
                activeElement?.click()
            }

            onFinishedKeyDown?.({
                e,
                activeElement,
                nextFocusedElement: elements[nextIndex],
                allElements: elements,
            })
        },
        [
            virtualFocus,
            virtualFocusedElementState,
            onFinishedKeyDown,
            recalculateFocusableElements,
            gridPosition.row,
            gridPosition.column,
            setVirtualFocusedElement,
        ]
    )

    const contextValue = useMemo(
        () => ({
            containerRef,
            registerGroupItem,
            unregisterGroupItem,
            focusGroupItem,
        }),
        [registerGroupItem, unregisterGroupItem, focusGroupItem]
    )

    // Keep internal maps in sync and refresh sticky row when children change.
    useEffect(() => {
        recalculateFocusableElements()

        // If we have a current focus, align sticky row to its latest data-row
        const active = (virtualFocus ? virtualFocusedElementState : (document.activeElement as HTMLElement)) || null
        if (active && containerRef.current?.contains(active)) {
            const rAttr = active.getAttribute('data-row')
            if (rAttr != null) {
                stickyRowRef.current = parseInt(rAttr, 10)
            }
            // If using virtual focus, ensure highlight stays on the same element
            if (virtualFocus && virtualFocusedElementState) {
                // If the element still exists, re-mark it as focused to avoid losing styling
                virtualFocusedElementState.setAttribute('data-focused', 'true')
            }
        }

        if (autoSelectFirst && !suppressAutoFocus.current) {
            focusFirstItem()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [children, autoSelectFirst]) // oxlint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (focusedElement) {
            focusedElement.focus()
            const rAttr = focusedElement.getAttribute('data-row')
            if (rAttr != null) {
                stickyRowRef.current = parseInt(rAttr, 10)
            }
        }
    }, [focusedElement])

    return (
        <ListBoxContext.Provider value={contextValue}>
            <div
                ref={containerRef}
                role="listbox"
                tabIndex={0}
                onKeyDown={handleKeyDown}
                className={cn(className)}
                aria-orientation="vertical"
                {...props}
            >
                {children}
            </div>
        </ListBoxContext.Provider>
    )
})

InnerListBox.displayName = 'ListBox'

/** ListBox.Item */

export interface ListBoxItemProps extends React.LiHTMLAttributes<HTMLLIElement> {
    children: ReactNode
    asChild?: boolean
    virtualFocusIgnore?: boolean
    focusFirst?: boolean
    // Used for left/right navigation
    row?: number
    column?: number
    // Unique key for focus persistence
    focusKey?: string
    // Index within a group (when inside ListBox.Group)
    index?: number
}

const ListBoxItem = forwardRef<HTMLLIElement, ListBoxItemProps>(
    (
        { children, asChild, onClick, virtualFocusIgnore, focusFirst, row, column, focusKey, index, ...props },
        ref
    ): JSX.Element => {
        const { containerRef } = useContext(ListBoxContext)
        const groupContext = useContext(ListBoxGroupContext)

        const handleFocus = (e: React.FocusEvent): void => {
            e.currentTarget.setAttribute('data-focused', 'true')
            // after setting data-focused...
            const rowAttr = (e.currentTarget as HTMLElement).getAttribute('data-row')
            if (rowAttr != null) {
                // reach up to the provider via a custom event (no context change needed)
                ;(e.currentTarget.closest('[role="listbox"]') as HTMLElement | null)?.dispatchEvent(
                    new CustomEvent('listbox:setStickyRow', {
                        detail: { row: parseInt(rowAttr, 10) },
                        bubbles: true,
                    })
                )
            }

            // Track all focus keys for history
            const currentFocusKey = (e.currentTarget as HTMLElement).getAttribute('data-focus-key')
            if (currentFocusKey) {
                ;(e.currentTarget.closest('[role="listbox"]') as HTMLElement | null)?.dispatchEvent(
                    new CustomEvent('listbox:setFocusKey', {
                        detail: {
                            focusKey: currentFocusKey,
                            isContent: !currentFocusKey.startsWith('show-all-'),
                        },
                        bubbles: true,
                    })
                )
            }
            containerRef?.current?.querySelectorAll('[data-listbox-item]').forEach((el: Element) => {
                if (el !== e.currentTarget) {
                    el.setAttribute('data-focused', 'false')
                }
            })
        }

        const handleBlur = (e: React.FocusEvent): void => {
            e.currentTarget.setAttribute('data-focused', 'false')
        }

        const handleItemClick = (e: React.MouseEvent): void => {
            e.currentTarget.setAttribute('aria-current', 'true')
            containerRef?.current?.querySelectorAll('[data-listbox-item]').forEach((el: Element) => {
                if (el !== e.currentTarget) {
                    el.setAttribute('aria-current', 'false')
                }
            })

            if (onClick) {
                onClick(e as React.MouseEvent<HTMLLIElement, MouseEvent>)
            }
        }

        // Register with group if inside a group and index is provided
        const elementRef = useRef<HTMLLIElement>(null)

        useEffect(() => {
            if (groupContext && index !== undefined && elementRef.current) {
                groupContext.registerItem(index, elementRef.current)
                return () => {
                    groupContext.unregisterItem(index)
                }
            }
        }, [groupContext, index])

        // Callback ref to capture the actual DOM element
        const setElementRef = useCallback(
            (element: HTMLLIElement | null) => {
                ;(elementRef as React.MutableRefObject<HTMLLIElement | null>).current = element

                // Also forward to the provided ref if it exists
                if (ref) {
                    if (typeof ref === 'function') {
                        ref(element)
                    } else {
                        ;(ref as React.MutableRefObject<HTMLLIElement | null>).current = element
                    }
                }
            },
            [ref]
        )

        const itemProps = useMemo(
            () => ({
                'data-listbox-item': 'true',
                'data-focused': 'false',
                'aria-current': false,
                'aria-selected': false,
                ...(row !== undefined ? { 'data-row': row } : {}),
                ...(column !== undefined ? { 'data-column': column } : {}),
                ...(focusKey !== undefined ? { 'data-focus-key': focusKey } : {}),
                tabIndex: -1,
                role: 'option',
                onClick: handleItemClick,
                onFocus: handleFocus,
                onBlur: handleBlur,
                ref: setElementRef,
                ...(virtualFocusIgnore ? { 'data-virtual-focus-ignore': 'true' } : {}),
                ...(focusFirst ? { 'data-focus-first': 'true' } : {}),
                ...props,
            }),
            [
                handleItemClick,
                handleFocus,
                handleBlur,
                setElementRef,
                virtualFocusIgnore,
                focusFirst,
                props,
                row,
                column,
                focusKey,
                index,
            ]
        )

        if (asChild && isValidElement(children)) {
            return cloneElement(children as React.ReactElement, {
                ...children.props,
                ...itemProps,
                onClick: (e: React.MouseEvent) => {
                    handleItemClick(e)
                    if (children.props.onClick) {
                        children.props.onClick(e)
                    }
                },
                className: cn(children.props.className, props.className),
            })
        }

        return <li {...itemProps}>{children}</li>
    }
)

ListBoxItem.displayName = 'ListBox.Item'

/** ListBox.Group */

export interface ListBoxGroupProps {
    children: ReactNode
    groupId?: string
}

let groupIdCounter = 0

const ListBoxGroup = forwardRef<ListBoxGroupHandle, ListBoxGroupProps>(
    ({ children, groupId: providedGroupId }, ref): JSX.Element => {
        const { registerGroupItem, unregisterGroupItem, focusGroupItem } = useContext(ListBoxContext)
        const groupId = useMemo(() => providedGroupId || `group-${groupIdCounter++}`, [providedGroupId])
        const groupItems = useRef<Map<number, HTMLLIElement>>(new Map())
        const currentFocusedIndex = useRef<number | null>(null)

        const registerItem = useCallback(
            (index: number, element: HTMLLIElement) => {
                groupItems.current.set(index, element)
                registerGroupItem?.(groupId, index, element)
            },
            [groupId, registerGroupItem]
        )

        const unregisterItem = useCallback(
            (index: number) => {
                groupItems.current.delete(index)
                unregisterGroupItem?.(groupId, index)
            },
            [groupId, unregisterGroupItem]
        )

        const resumeFocus = useCallback(
            (index: number): boolean => {
                const availableIndices = Array.from(groupItems.current.keys()).sort((a, b) => a - b)

                // Try to focus the item at the given index
                if (focusGroupItem?.(groupId, index)) {
                    currentFocusedIndex.current = index
                    return true
                }

                // If that fails, try to focus the closest available item

                // Find the closest index to the requested one
                let closestIndex = availableIndices[0]
                let minDistance = Math.abs(availableIndices[0] - index)

                for (const availableIndex of availableIndices) {
                    const distance = Math.abs(availableIndex - index)
                    if (distance < minDistance) {
                        minDistance = distance
                        closestIndex = availableIndex
                    }
                }

                if (focusGroupItem?.(groupId, closestIndex)) {
                    currentFocusedIndex.current = closestIndex
                    return true
                }

                return false
            },
            [groupId, focusGroupItem]
        )

        const getFocusedIndex = useCallback((): number | null => {
            return currentFocusedIndex.current
        }, [])

        useImperativeHandle(
            ref,
            () => ({
                resumeFocus,
                getFocusedIndex,
            }),
            [resumeFocus, getFocusedIndex]
        )

        const groupContextValue = useMemo(
            () => ({
                groupId,
                registerItem,
                unregisterItem,
            }),
            [groupId, registerItem, unregisterItem]
        )

        return <ListBoxGroupContext.Provider value={groupContextValue}>{children}</ListBoxGroupContext.Provider>
    }
)

ListBoxGroup.displayName = 'ListBox.Group'

export const ListBox = Object.assign(InnerListBox, {
    Item: ListBoxItem,
    Group: ListBoxGroup,
})
