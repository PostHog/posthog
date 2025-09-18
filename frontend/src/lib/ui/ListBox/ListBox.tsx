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
    }, [])

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
            const currentIndex = elements.indexOf(activeElement!)
            let nextIndex = currentIndex

            if (virtualFocus) {
                elements.forEach((el) => el.removeAttribute('data-focused'))
            }

            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault()

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
            } else if (e.key === 'Home' || e.key === 'End') {
                e.preventDefault()
                if (e.key === 'Home') {
                    const firstFocusElement = elements.find((el) => el.getAttribute('data-focus-first') === 'true')
                    nextIndex = firstFocusElement ? elements.indexOf(firstFocusElement) : 0
                } else {
                    nextIndex = elements.length - 1
                }
            }

            if (virtualFocus) {
                setVirtualFocusedElement(elements[nextIndex])
                elements[nextIndex]?.setAttribute('data-focused', 'true')
            } else {
                elements[nextIndex]?.focus()
            }

            elements[nextIndex]?.scrollIntoView({ block: 'nearest' })

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
        [virtualFocus, virtualFocusedElement, onFinishedKeyDown, recalculateFocusableElements]
    )

    const contextValue = useMemo(() => ({ containerRef }), [])

    useEffect(() => {
        recalculateFocusableElements()
        if (autoSelectFirst) {
            focusFirstItem()
        }
    }, [children, autoSelectFirst, focusFirstItem]) // oxlint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (focusedElement) {
            focusedElement.focus()
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
}

const ListBoxItem = forwardRef<HTMLLIElement, ListBoxItemProps>(
    ({ children, asChild, onClick, virtualFocusIgnore, focusFirst, ...props }, ref): JSX.Element => {
        const { containerRef } = useContext(ListBoxContext)

        const handleFocus = (e: React.FocusEvent): void => {
            e.currentTarget.setAttribute('data-focused', 'true')
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
            [handleItemClick, handleFocus, handleBlur, ref, virtualFocusIgnore, focusFirst, props]
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
