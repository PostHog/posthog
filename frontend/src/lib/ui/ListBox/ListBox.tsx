import { cn } from 'lib/utils/css-classes'
import React, {
    cloneElement,
    createContext,
    forwardRef,
    isValidElement,
    ReactNode,
    useContext,
    useEffect,
    useImperativeHandle,
    useRef,
    useState,
} from 'react'

interface ListBoxContextType {
    containerRef: React.RefObject<HTMLDivElement> | null
}

const ListBoxContext = createContext<ListBoxContextType>({ containerRef: null })

interface ListBoxProps extends React.HTMLAttributes<HTMLDivElement> {
    children: ReactNode
    className?: string
    focusedElement?: HTMLElement | null
    // If true, the listbox will use virtual focus instead of the default browser focus
    // Useful for when you need to keep focus, but allow keyboard navigation in lists
    virtualFocus?: boolean
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

export interface ListBoxHandle {
    getFocusableElements: () => HTMLElement[]
    focusFirstElement: () => void
    focusNthElement: (index: number) => void
}

const ListBoxInner = forwardRef<ListBoxHandle, ListBoxProps>(
    ({ children, className, onFinishedKeyDown, focusedElement, virtualFocus = false, ...props }, ref) => {
        const containerRef = useRef<HTMLDivElement>(null)
        const focusableElements = useRef<HTMLElement[]>([])
        const [virtualFocusedElement, setVirtualFocusedElement] = useState<HTMLElement | null>(null)

        function recalculateFocusableElements(): void {
            focusableElements.current = Array.from(
                containerRef.current?.querySelectorAll<HTMLElement>('[data-listbox-item]') || []
            ).filter((el) => !(el.hidden || window.getComputedStyle(el).display === 'none'))
        }

        useImperativeHandle(ref, () => ({
            getFocusableElements: () => focusableElements.current,
            focusFirstElement: () => {
                if (virtualFocus) {
                    setVirtualFocusedElement(focusableElements.current[0])
                    focusableElements.current[0]?.setAttribute('data-focused', 'true')
                } else {
                    focusableElements.current[0]?.focus()
                }
            },
            focusNthElement: (index: number) => {
                if (virtualFocus) {
                    setVirtualFocusedElement(focusableElements.current[index])
                    focusableElements.current[index]?.setAttribute('data-focused', 'true')
                } else {
                    focusableElements.current[index]?.focus()
                }
            },
        }))

        useEffect(() => {
            recalculateFocusableElements()
        }, [children])

        useEffect(() => {
            if (focusedElement) {
                focusedElement.focus()
            }
        }, [focusedElement])

        const handleKeyDown = (e: React.KeyboardEvent): void => {
            recalculateFocusableElements()
            const elements = focusableElements.current
            if (!elements.length) {
                return
            }

            const activeElement = virtualFocus
                ? (virtualFocusedElement as HTMLElement)
                : (document.activeElement as HTMLElement)
            const currentIndex = elements.indexOf(activeElement)
            let nextIndex = currentIndex

            // If virtual focus is enabled, remove the data-focused attribute from all elements
            if (virtualFocus) {
                elements.forEach((el) => el.removeAttribute('data-focused'))
            }

            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault()
                nextIndex = (currentIndex + (e.key === 'ArrowDown' ? 1 : -1) + elements.length) % elements.length
                if (virtualFocus) {
                    setVirtualFocusedElement(elements[nextIndex])
                    elements[nextIndex]?.setAttribute('data-focused', 'true')
                } else {
                    elements[nextIndex]?.focus()
                }
            } else if (e.key === 'Home' || e.key === 'End') {
                e.preventDefault()
                nextIndex = e.key === 'Home' ? 0 : elements.length - 1
                if (virtualFocus) {
                    setVirtualFocusedElement(elements[nextIndex])
                    elements[nextIndex]?.setAttribute('data-focused', 'true')
                } else {
                    elements[nextIndex]?.focus()
                }
            }

            if (e.key === 'Enter') {
                e.preventDefault()
                activeElement?.click()
            }

            if (onFinishedKeyDown) {
                onFinishedKeyDown({
                    e,
                    activeElement,
                    nextFocusedElement: elements[nextIndex],
                    allElements: elements,
                })
            }
        }

        /** Recalculate focusable elements whenever the DOM updates */
        useEffect(() => {
            recalculateFocusableElements()
        }, [children])

        useEffect(() => {
            if (focusedElement) {
                focusedElement.focus()
            }
        }, [focusedElement])

        return (
            <ListBoxContext.Provider value={{ containerRef }}>
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
    }
)

ListBoxInner.displayName = 'ListBox'

interface ListBoxItemProps extends React.LiHTMLAttributes<HTMLLIElement> {
    children: ReactNode
    asChild?: boolean
}

const ListBoxItem = forwardRef<HTMLLIElement, ListBoxItemProps>(
    ({ children, asChild, onClick, ...props }, ref): JSX.Element => {
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

        const itemProps = {
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
            ...props,
        }

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

interface ListBoxComponent extends React.ForwardRefExoticComponent<ListBoxProps & React.RefAttributes<ListBoxHandle>> {
    Item: typeof ListBoxItem
}

const ListBox = ListBoxInner as ListBoxComponent
ListBox.Item = ListBoxItem

export { ListBox }
