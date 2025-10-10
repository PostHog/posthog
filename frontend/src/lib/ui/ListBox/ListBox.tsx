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
}

/** Context to expose container ref to child Items */
interface ListBoxContextType {
    containerRef: React.RefObject<HTMLDivElement> | null
}

const ListBoxContext = createContext<ListBoxContextType>({ containerRef: null })

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
    const [virtualFocusedElement, setVirtualFocusedElement] = useState<HTMLElement | null>(null)

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

    useEffect(() => {
        const el = containerRef.current
        if (!el) {
            return
        }
        const handler = (ev: Event): void => {
            const row = (ev as CustomEvent).detail?.row
            if (typeof row === 'number' && row >= 0) {
                stickyRowRef.current = row
            }
        }
        el.addEventListener('listbox:setStickyRow', handler as EventListener)
        return () => el.removeEventListener('listbox:setStickyRow', handler as EventListener)
    }, [])

    const gridPosition = useMemo<{ row: number; column: number }>(() => {
        const activeElement = virtualFocus ? virtualFocusedElement : (document.activeElement as HTMLElement)
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
    }, [virtualFocus, virtualFocusedElement])

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
    }, [virtualFocus, recalculateFocusableElements])

    const getFocusableElementsCount = useCallback(() => {
        recalculateFocusableElements()
        const elements = focusableElements.current
        if (!elements.length) {
            return 0
        }
        return elements.length
    }, [recalculateFocusableElements])

    useImperativeHandle(
        ref,
        () => ({
            recalculateFocusableElements,
            focusFirstItem,
            getFocusableElementsCount,
        }),
        [recalculateFocusableElements, focusFirstItem, getFocusableElementsCount]
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

            const activeElement = virtualFocus ? virtualFocusedElement : (document.activeElement as HTMLElement)
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
            virtualFocusedElement,
            onFinishedKeyDown,
            recalculateFocusableElements,
            gridPosition.row,
            gridPosition.column,
        ]
    )

    const contextValue = useMemo(() => ({ containerRef }), [])

    // Keep internal maps in sync and refresh sticky row when children change.
    useEffect(() => {
        recalculateFocusableElements()

        // If we have a current focus, align sticky row to its latest data-row
        const active = (virtualFocus ? virtualFocusedElement : (document.activeElement as HTMLElement)) || null
        if (active && containerRef.current?.contains(active)) {
            const rAttr = active.getAttribute('data-row')
            if (rAttr != null) {
                stickyRowRef.current = parseInt(rAttr, 10)
            }
            // If using virtual focus, ensure highlight stays on the same element
            if (virtualFocus && virtualFocusedElement) {
                // If the element still exists, re-mark it as focused to avoid losing styling
                virtualFocusedElement.setAttribute('data-focused', 'true')
            }
        }

        if (autoSelectFirst) {
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
}

const ListBoxItem = forwardRef<HTMLLIElement, ListBoxItemProps>(
    ({ children, asChild, onClick, virtualFocusIgnore, focusFirst, row, column, ...props }, ref): JSX.Element => {
        const { containerRef } = useContext(ListBoxContext)

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

        const itemProps = useMemo(
            () => ({
                'data-listbox-item': 'true',
                'data-focused': 'false',
                'aria-current': false,
                'aria-selected': false,
                ...(row !== undefined ? { 'data-row': row } : {}),
                ...(column !== undefined ? { 'data-column': column } : {}),
                tabIndex: -1,
                role: 'option',
                onClick: handleItemClick,
                onFocus: handleFocus,
                onBlur: handleBlur,
                ref,
                ...(virtualFocusIgnore ? { 'data-virtual-focus-ignore': 'true' } : {}),
                ...(focusFirst ? { 'data-focus-first': 'true' } : {}),
                ...props,
            }),
            [handleItemClick, handleFocus, handleBlur, ref, virtualFocusIgnore, focusFirst, props, row, column]
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

export const ListBox = Object.assign(InnerListBox, {
    Item: ListBoxItem,
})
