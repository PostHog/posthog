import { cn } from 'lib/utils/css-classes'
import React, { cloneElement, forwardRef, isValidElement, ReactNode, useEffect, useRef } from 'react'

interface ListBoxProps extends React.HTMLAttributes<HTMLDivElement> {
    children: ReactNode
    className?: string
    focusedElement?: HTMLElement | null
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

export const ListBox = ({
    children,
    className,
    onFinishedKeyDown,
    focusedElement,
    ...props
}: ListBoxProps): JSX.Element => {
    const containerRef = useRef<HTMLDivElement>(null)
    const focusableElements = useRef<HTMLElement[]>([])

    /** Fetches all valid focusable elements inside ListBox */
    function recalculateFocusableElements(): void {
        focusableElements.current = Array.from(
            containerRef.current?.querySelectorAll<HTMLElement>('[data-listbox-item]') || []
        ).filter((el) => !(el.hidden || window.getComputedStyle(el).display === 'none'))
    }

    /** Handle Arrow navigation */
    const handleKeyDown = (e: React.KeyboardEvent): void => {
        recalculateFocusableElements()
        const elements = focusableElements.current
        if (!elements.length) {
            return
        }

        const activeElement = document.activeElement as HTMLElement
        const currentIndex = elements.indexOf(activeElement)
        let nextIndex = currentIndex

        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault()
            nextIndex = (currentIndex + (e.key === 'ArrowDown' ? 1 : -1) + elements.length) % elements.length
            elements[nextIndex]?.focus()
        }

        if (e.key === 'Enter') {
            e.preventDefault()
            activeElement?.click()
        }

        if (onFinishedKeyDown) {
            onFinishedKeyDown({ e, activeElement, nextFocusedElement: elements[nextIndex], allElements: elements })
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
        <div
            ref={containerRef}
            role="listbox"
            tabIndex={0}
            onKeyDown={handleKeyDown}
            className={cn(className)}
            {...props}
        >
            {children}
        </div>
    )
}

ListBox.displayName = 'ListBox'

interface ListBoxItemProps extends React.LiHTMLAttributes<HTMLLIElement> {
    children: ReactNode
    asChild?: boolean
}

ListBox.Item = forwardRef<HTMLLIElement, ListBoxItemProps>(
    ({ children, asChild, onClick, ...props }, ref): JSX.Element => {
        const handleFocus = (e: React.FocusEvent): void => {
            e.currentTarget.setAttribute('data-focused', 'true')

            document.querySelectorAll('[data-listbox-item]').forEach((el) => {
                if (el !== e.currentTarget) {
                    el.setAttribute('data-focused', 'false')
                }
            })
        }

        const handleItemClick = (e: React.MouseEvent): void => {
            // Set `aria-current` on the clicked item
            e.currentTarget.setAttribute('aria-current', 'true')
            document.querySelectorAll('[data-listbox-item]').forEach((el) => {
                if (el !== e.currentTarget) {
                    el.setAttribute('aria-current', 'false')
                }
            })

            // Ensure `onClick` is forwarded when `asChild` is used
            if (onClick) {
                onClick(e as React.MouseEvent<HTMLLIElement, MouseEvent>)
            }
        }

        const itemProps = {
            'data-listbox-item': 'true',
            'data-focused': 'false',
            'aria-current': false,
            tabIndex: -1,
            role: 'option',
            onClick: handleItemClick,
            onFocus: handleFocus,
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

ListBox.Item.displayName = 'ListBox.Item'
